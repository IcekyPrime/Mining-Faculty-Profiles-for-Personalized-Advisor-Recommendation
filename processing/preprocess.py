"""处理层 · 预处理：清洗、论文年份/作者抽取、中英文姓名索引、合作网络构建。"""
import json
import os
import re
import sqlite3

from pypinyin import lazy_pinyin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get('MENTOR_DB_PATH') or os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')
os.makedirs(EXP, exist_ok=True)

RE_YEAR = re.compile(r'\b(?:19|20)\d{2}\b')
MIN_YEAR = 1950
MAX_YEAR = 2027


def pinyin_forms(name):
    """返回姓名的小写英文形式集合，如 陈海波 -> {chen haibo, haibo chen}"""
    py = lazy_pinyin(name or '')
    if not py or len(py) < 2:
        return set()
    surname, given = py[0], ''.join(py[1:])
    return {f'{surname} {given}', f'{given} {surname}'}


def norm(s):
    return re.sub(r'[^a-z]', '', (s or '').lower())


def build_pinyin_index(conn):
    """为所有教师构建 拼音 -> teacher_id 索引，并补齐缺失的 name_pinyin。"""
    index = {}
    for tid, name, np_ in conn.execute("SELECT id, name, name_pinyin FROM teachers").fetchall():
        forms = pinyin_forms(name)
        for f in forms:
            index.setdefault(norm(f), set()).add(tid)
        if not np_:
            conn.execute("UPDATE teachers SET name_pinyin=? WHERE id=?",
                         (next(iter(forms), None), tid))
    conn.commit()
    return index


def extract_authors(title):
    """从论文标题串中抽取英文作者名列表（兼容多种格式：作者在标题前/后、含换行）。"""
    if not title:
        return []
    title = re.sub(r'\s+', ' ', title)          # 归一化换行/空白
    m = re.match(r'^\s*\[[^\]]*\]\s*', title)   # 去掉 [ venue ] 前缀
    rest = title[m.end():] if m else title
    # 去掉会议/期刊描述段，减少误抽（保留标题+作者部分）
    rest = re.split(r'\.\s+(?=(?:The|In|Proceedings|Proc\.|ACM|IEEE|USENIX|Springer|International|Journal|Conference|Symposium|Workshop)\b)', rest)[0]
    stop = {'The', 'In', 'Proceedings', 'Conference', 'Symposium', 'Journal', 'Workshop',
            'USENIX', 'ACM', 'IEEE', 'Springer', 'International', 'And', 'For', 'A', 'An',
            'On', 'Of', 'With', 'Using', 'Towards', 'Based', 'Learning', 'System', 'Systems'}
    names = re.findall(r'\b[A-Z][a-z][a-zA-Z\-]*(?:\s+[A-Z][a-zA-Z\-]+){1,2}\b', rest)
    out, seen = [], set()
    for n in names:
        if n.split()[0] in stop:
            continue
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def extract_year(title):
    """取标题/引用串中最后一个合理的四位年份。

    论文引用串里靠前的四位数常是卷号/页码，出版年一般在末尾；
    因此收集全部候选后取最后一个落在 1950–2027 区间的值。
    """
    candidates = []
    for match in RE_YEAR.finditer(title or ''):
        year = int(match.group(0))
        if MIN_YEAR <= year <= MAX_YEAR:
            candidates.append(year)
    return candidates[-1] if candidates else None


def build_authors_graph(conn, pinyin_index):
    """基于 papers.authors 完整作者列表构建全学院合作网络。

    原版只从官网标题串里抽 CS 作者，导致非计算机学院没有合作边；
    恢复 ``authors`` 后可以直接用结构化作者列表补全，覆盖 676 位教师。
    """
    edges = {}
    papers_n = 0
    teachers = set()
    for row in conn.execute(
        """SELECT p.teacher_id, p.authors FROM papers p
           JOIN teachers t ON t.id=p.teacher_id
           WHERE p.authors IS NOT NULL AND TRIM(p.authors)<>''"""
    ):
        try:
            authors = json.loads(row["authors"] or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(authors, list) or not authors:
            continue
        papers_n += 1
        groups = []
        for author in authors:
            ids = pinyin_index.get(norm(str(author))) or set()
            if ids:
                groups.append(ids)
        if not groups:
            continue
        matched = set().union(*groups)
        tid = row["teacher_id"]
        matched.discard(tid)
        teachers.update(matched)
        teachers.add(tid)
        for other in matched:
            # 同名作者无法区分时，不连边
            if any(tid in group and other in group for group in groups):
                continue
            a, b = (tid, other) if tid < other else (other, tid)
            edges[(a, b)] = edges.get((a, b), 0) + 1
    return edges, len(teachers), papers_n


def build_collab_graph(conn, pinyin_index):
    """基于 CS 论文作者列表构建合作网络（仅匹配到本库教师的边）。"""
    edges = {}
    rows = conn.execute("""SELECT p.teacher_id, p.title FROM papers p
                           JOIN teachers t ON p.teacher_id=t.id WHERE t.college='计算机学院'""").fetchall()
    for tid, title in rows:
        authors = extract_authors(title)
        matched = set()
        for a in authors:
            ids = pinyin_index.get(norm(a))
            if ids:
                matched.update(ids)
        matched.discard(tid)
        for other in matched:
            a, b = (tid, other) if tid < other else (other, tid)
            edges[(a, b)] = edges.get((a, b), 0) + 1
    return edges


def load_existing_edges():
    """读取已有的 collab_edges.csv。

    仓库没有提交 data/raw 原始抓取文件时，arXiv/Crossref 图无法从源重建；
    此时沿用上游已生成的合作边，避免把 2,347 条边静默降级成 167 条。
    """
    path = os.path.join(EXP, 'collab_edges.csv')
    if not os.path.exists(path):
        return {}
    edges = {}
    with open(path, encoding='utf-8') as handle:
        next(handle, None)
        for line in handle:
            parts = line.strip().split(',')
            if len(parts) != 3:
                continue
            try:
                a, b, weight = int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                continue
            edges[(a, b)] = weight
    return edges


def build_author_graph(pinyin_index, conn, subdir, papers_key):
    """基于论文完整作者列表构建合作边（arXiv / Crossref 通用，覆盖非计算机学院）。"""
    edges = {}
    dir_ = os.path.join(ROOT, 'data', 'raw', subdir)
    if not os.path.isdir(dir_):
        return edges, 0, 0
    colleges = dict(conn.execute("SELECT id, college FROM teachers").fetchall())
    teachers, papers_n = 0, 0
    for fn in sorted(os.listdir(dir_)):
        if not fn.endswith('.json'):
            continue
        try:
            tid = int(fn[:-5])
        except ValueError:
            continue
        if colleges.get(tid) == '计算机学院':
            continue
        try:
            with open(os.path.join(dir_, fn), encoding='utf-8') as handle:
                data = json.load(handle)
        except Exception:
            continue
        papers = data.get(papers_key) or []
        if not papers:
            continue
        teachers += 1
        papers_n += len(papers)
        for paper in papers:
            groups = [pinyin_index[norm(a)] for a in paper.get('authors') or []
                      if norm(a) in pinyin_index]
            matched = set().union(*groups) if groups else set()
            matched.discard(tid)
            for other in matched:
                # 同一英文姓名对应多位教师（同音）时无法区分，不连边
                if any(tid in group and other in group for group in groups):
                    continue
                edge = (tid, other) if tid < other else (other, tid)
                edges[edge] = edges.get(edge, 0) + 1
    return edges, teachers, papers_n


def build_arxiv_graph(pinyin_index, conn):
    return build_author_graph(pinyin_index, conn, 'arxiv', 'arxiv_papers')


def build_crossref_graph(pinyin_index, conn):
    return build_author_graph(pinyin_index, conn, 'crossref', 'works')


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    print('构建拼音索引 ...')
    index = build_pinyin_index(conn)
    print(f'  拼音索引覆盖 {len(index)} 个姓名形式')

    print('抽取/修复论文年份 ...')
    n_year = 0
    # 修复空值、旧正则截断出的 19/20、以及超出 1950–2027 的异常年份；
    # 正常四位年份（Semantic Scholar 给出的）保持不变，找不到年份时置空。
    rows = conn.execute(
        "SELECT id, title, year FROM papers WHERE year IS NULL OR year < ? "
        "OR year > ?", (MIN_YEAR, MAX_YEAR)
    ).fetchall()
    for pid, title, old in rows:
        y = extract_year(title)
        if y != old:
            conn.execute("UPDATE papers SET year=? WHERE id=?", (y, pid))
            n_year += 1
    conn.commit()
    print(f'  修复/清理年份 {n_year} 篇')

    print('构建合作网络 ...')
    title_edges = build_collab_graph(conn, index)
    edges = dict(title_edges)
    print(f'  官网标题作者：合作边 {len(edges)} 条，涉及 {len({x for e in edges for x in e})} 位教师')

    author_edges, n_teachers, n_papers = build_authors_graph(conn, index)
    print(f'  papers.authors：{n_teachers} 位教师、{n_papers} 篇，合作边 {len(author_edges)} 条')
    for key, weight in author_edges.items():
        edges[key] = edges.get(key, 0) + weight

    arxiv_edges, a_teachers, a_papers = build_arxiv_graph(index, conn)
    print(f'  arXiv 原始论文：{a_teachers} 位教师、{a_papers} 篇，合作边 {len(arxiv_edges)} 条')
    crossref_edges, c_teachers, c_papers = build_crossref_graph(index, conn)
    print(f'  Crossref 原始作品：{c_teachers} 位教师、{c_papers} 条，合作边 {len(crossref_edges)} 条')
    for source in (arxiv_edges, crossref_edges):
        for key, weight in source.items():
            edges[key] = edges.get(key, 0) + weight

    if not arxiv_edges and not crossref_edges:
        existing = load_existing_edges()
        if len(existing) > len(edges):
            print(f'  原始抓取文件缺失，沿用已有合作边 {len(existing)} 条')
            # 已有边是上游已核对的基线，不因为当前只能抽出少量作者边就丢掉。
            for key, weight in edges.items():
                existing.setdefault(key, weight)
            edges = existing

    print(f'  合并后：合作边 {len(edges)} 条，涉及 {len({x for e in edges for x in e})} 位教师')

    # 保存中间结果
    with open(os.path.join(EXP, 'pinyin_index.json'), 'w', encoding='utf-8') as f:
        json.dump({k: sorted(v) for k, v in index.items()}, f, ensure_ascii=False)
    with open(os.path.join(EXP, 'collab_edges.csv'), 'w', encoding='utf-8') as f:
        lines = ['src,dst,weight\n']
        lines.extend(f'{a},{b},{w}\n'
                     for (a, b), w in sorted(edges.items(), key=lambda x: -x[1]))
        f.writelines(lines)
    with open(os.path.join(EXP, 'collab_summary.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'title_edges': len(title_edges),
            'author_edges': len(author_edges),
            'arxiv_edges': len(arxiv_edges),
            'crossref_edges': len(crossref_edges),
            'merged_edges': len(edges),
            'nodes': len({x for e in edges for x in e}),
            'author_teachers': n_teachers,
            'author_papers': n_papers,
            'arxiv_teachers': a_teachers,
            'arxiv_papers': a_papers,
            'crossref_teachers': c_teachers,
            'crossref_papers': c_papers,
        }, f, ensure_ascii=False, indent=1)
    print(f'中间结果已写入 {EXP}')
    conn.close()


if __name__ == '__main__':
    main()
