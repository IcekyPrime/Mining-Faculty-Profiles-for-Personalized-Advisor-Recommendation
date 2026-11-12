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
        matched = set()
        for a in authors:
            ids = pinyin_index.get(norm(a))
            if ids:
                matched.update(ids)
        if tid in matched:
            matched.remove(tid)
        for other in matched:
            a, b = (tid, other) if tid < other else (other, tid)
            edges[(a, b)] = edges.get((a, b), 0) + 1
    return edges


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
    edges = build_collab_graph(conn, index)
    print(f'  合作边 {len(edges)} 条，涉及 {len({x for e in edges for x in e})} 位教师')

    # 保存中间结果
    with open(os.path.join(EXP, 'pinyin_index.json'), 'w', encoding='utf-8') as f:
        json.dump({k: sorted(v) for k, v in index.items()}, f, ensure_ascii=False)
    with open(os.path.join(EXP, 'collab_edges.csv'), 'w', encoding='utf-8') as f:
        f.write('src,dst,weight\n')
        for (a, b), w in sorted(edges.items(), key=lambda x: -x[1]):
            f.write(f'{a},{b},{w}\n')
    print(f'中间结果已写入 {EXP}')
    conn.close()


if __name__ == '__main__':
    main()
