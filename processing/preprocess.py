"""处理层 · 预处理：清洗、论文年份/作者抽取、中英文姓名索引、合作网络构建。"""
import sqlite3, re, json, os
from pypinyin import lazy_pinyin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')
os.makedirs(EXP, exist_ok=True)

RE_YEAR = re.compile(r'(19|20)\d{2}')


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
    m = RE_YEAR.findall(title or '')
    if m:
        return int(m[-1])
    return None


def build_collab_graph(conn, pinyin_index):
    """基于 CS 论文作者列表构建合作网络（仅匹配到本库教师的边）。"""
    edges = {}
    missing = 0
    rows = conn.execute("""SELECT p.teacher_id, p.title FROM papers p
                           JOIN teachers t ON p.teacher_id=t.id WHERE t.college='计算机学院'""").fetchall()
    for tid, title in rows:
        authors = extract_authors(title)
        groups = [pinyin_index[norm(a)] for a in authors if norm(a) in pinyin_index]
        matched = set().union(*groups) if groups else set()
        matched.discard(tid)
        for other in matched:
            # 同一英文姓名对应多位教师（同音）时无法区分，不连边
            if any(tid in g and other in g for g in groups):
                continue
            a, b = (tid, other) if tid < other else (other, tid)
            edges[(a, b)] = edges.get((a, b), 0) + 1
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
            data = json.load(open(os.path.join(dir_, fn), encoding='utf-8'))
        except Exception:
            continue
        papers = data.get(papers_key) or []
        if not papers:
            continue
        teachers += 1
        papers_n += len(papers)
        for p in papers:
            groups = [pinyin_index[norm(a)] for a in p.get('authors') or []
                      if norm(a) in pinyin_index]
            matched = set().union(*groups) if groups else set()
            matched.discard(tid)
            for other in matched:
                # 同一英文姓名对应多位教师（同音）时无法区分，不连边
                if any(tid in g and other in g for g in groups):
                    continue
                edge = (tid, other) if tid < other else (other, tid)
                edges[edge] = edges.get(edge, 0) + 1
    return edges, teachers, papers_n


def build_arxiv_graph(pinyin_index, conn):
    """基于 arXiv 论文的完整作者列表构建合作边。"""
    return build_author_graph(pinyin_index, conn, 'arxiv', 'arxiv_papers')


def build_crossref_graph(pinyin_index, conn):
    """基于 Crossref 作品的完整作者列表构建合作边。"""
    return build_author_graph(pinyin_index, conn, 'crossref', 'works')


def main():
    conn = sqlite3.connect(DB)
    print('构建拼音索引 ...')
    index = build_pinyin_index(conn)
    print(f'  拼音索引覆盖 {len(index)} 个姓名形式')

    print('抽取论文年份 ...')
    n_year = 0
    for pid, title in conn.execute("SELECT id, title FROM papers WHERE year IS NULL").fetchall():
        y = extract_year(title)
        if y:
            conn.execute("UPDATE papers SET year=? WHERE id=?", (y, pid))
            n_year += 1
    conn.commit()
    print(f'  补齐年份 {n_year} 篇')

    print('构建合作网络 ...')
    cs_edges = build_collab_graph(conn, index)
    print(f'  官网论文：合作边 {len(cs_edges)} 条，涉及 {len({x for e in cs_edges for x in e})} 位教师')

    arxiv_edges, n_teachers, n_papers = build_arxiv_graph(index, conn)
    print(f'  arXiv 论文：{n_teachers} 位教师、{n_papers} 篇，合作边 {len(arxiv_edges)} 条')

    crossref_edges, c_teachers, c_papers = build_crossref_graph(index, conn)
    print(f'  Crossref 作品：{c_teachers} 位教师、{c_papers} 条，合作边 {len(crossref_edges)} 条')

    edges = dict(cs_edges)
    for source in (arxiv_edges, crossref_edges):
        for k, w in source.items():
            edges[k] = edges.get(k, 0) + w
    print(f'  合并后：合作边 {len(edges)} 条，涉及 {len({x for e in edges for x in e})} 位教师')

    # 保存中间结果
    with open(os.path.join(EXP, 'pinyin_index.json'), 'w', encoding='utf-8') as f:
        json.dump({k: sorted(v) for k, v in index.items()}, f, ensure_ascii=False)
    with open(os.path.join(EXP, 'collab_edges.csv'), 'w', encoding='utf-8') as f:
        f.write('src,dst,weight\n')
        for (a, b), w in sorted(edges.items(), key=lambda x: -x[1]):
            f.write(f'{a},{b},{w}\n')
    with open(os.path.join(EXP, 'collab_summary.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'cs_edges': len(cs_edges),
            'arxiv_edges': len(arxiv_edges),
            'crossref_edges': len(crossref_edges),
            'merged_edges': len(edges),
            'nodes': len({x for e in edges for x in e}),
            'arxiv_teachers': n_teachers,
            'arxiv_papers': n_papers,
            'crossref_teachers': c_teachers,
            'crossref_papers': c_papers,
        }, f, ensure_ascii=False, indent=1)
    print(f'中间结果已写入 {EXP}')
    conn.close()


if __name__ == '__main__':
    main()
