"""处理层 · 相似检索：Shingling + MinHash + LSH（自实现），召回研究方向相似的导师。"""
import sqlite3, json, os, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')

N_HASH = 100      # MinHash 签名长度
BANDS = 20        # LSH 带数
ROWS = N_HASH // BANDS  # 每带行数


def hash_family(i):
    def h(x):
        return int(hashlib.md5(f'{i}:{x}'.encode()).hexdigest(), 16)
    return h


def minhash(shingles):
    sig = []
    for i in range(N_HASH):
        h = hash_family(i)
        sig.append(min(h(s) for s in shingles) if shingles else 2**64)
    return sig


def band_key(sig, b):
    chunk = tuple(sig[b * ROWS:(b + 1) * ROWS])
    return hashlib.md5(repr(chunk).encode()).hexdigest()


def jaccard(a, b):
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT teacher_id, keywords FROM processing WHERE keywords IS NOT NULL").fetchall()
    data = {r['teacher_id']: set(json.loads(r['keywords'])) for r in rows}
    print(f'参与相似检索的教师 {len(data)} 人')

    # MinHash 签名
    sigs = {tid: minhash(shingles) for tid, shingles in data.items()}
    # LSH 分桶
    buckets = {}
    for tid, sig in sigs.items():
        for b in range(BANDS):
            buckets.setdefault((b, band_key(sig, b)), []).append(tid)

    # 候选对
    cand = set()
    for (b, key), tids in buckets.items():
        if len(tids) < 2:
            continue
        for i in range(len(tids)):
            for j in range(i + 1, len(tids)):
                a, b_ = tids[i], tids[j]
                if a != b_:
                    cand.add((min(a, b_), max(a, b_)))
    print(f'LSH 候选对 {len(cand)} 对')

    # 精确 Jaccard 过滤
    pairs = []
    for a, b in cand:
        j = jaccard(data[a], data[b])
        if j >= 0.25:
            pairs.append((a, b, round(j, 3)))
    pairs.sort(key=lambda x: -x[2])
    print(f'Jaccard≥0.25 的相似对 {len(pairs)} 对')

    name_map = dict(conn.execute("SELECT id, name FROM teachers").fetchall())
    with open(os.path.join(EXP, 'similar_pairs.json'), 'w', encoding='utf-8') as f:
        json.dump([[a, b, j] for a, b, j in pairs], f)
    print('\n相似度最高的 10 对：')
    for a, b, j in pairs[:10]:
        print(f"  {name_map.get(a)} <-> {name_map.get(b)} : {j}")
    conn.close()


if __name__ == '__main__':
    main()
