"""数据层主流程（五个目标学院版）。

流程：抓取五个学院（计算机 + 自动化与感知 + 集成电路 + 电气工程 + 人工智能）教师名录与详情页 ->
选课社区富化（课程/评分，学院以官网目录为准）-> Semantic Scholar 富化（学术指标）-> 导师筛选 -> 写库。

用法：
    python run_pipeline.py [--limit N]
"""
import argparse

from crawler import (cs_crawler, college_crawler, course_community,
                     scholar_client, faculty_crawler, config)
import db

TARGET_COLLEGES = ["计算机学院", "自动化与感知学院", "集成电路学院", "电气工程学院", "人工智能学院"]


def crawl_cs():
    teachers = cs_crawler.fetch_teacher_list()
    teachers = cs_crawler.crawl_details(teachers)
    for t in teachers:
        t["college"] = "计算机学院"
    return teachers


def crawl_college(name):
    teachers = college_crawler.fetch_teacher_list(name)
    teachers = college_crawler.crawl_details(name, teachers)
    for t in teachers:
        t["college"] = name
    return teachers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    all_teachers = []
    print("== 抓取 计算机学院 ==")
    all_teachers += crawl_cs()
    for name in TARGET_COLLEGES[1:]:
        print(f"== 抓取 {name} ==")
        all_teachers += crawl_college(name)

    print(f"合计 {len(all_teachers)} 人")
    if args.limit:
        all_teachers = all_teachers[: args.limit]
        print(f"  [debug] 仅处理前 {len(all_teachers)} 位")

    print("== 富化：选课社区 + Semantic Scholar + 导师筛选 ==")
    for i, t in enumerate(all_teachers):
        source_college = t.get("college")
        try:
            t.update(course_community.enrich_teacher(t))
        except Exception as e:
            print(f"  [选课社区] {t['name']}: {type(e).__name__}")
        t["college"] = source_college  # 学院以官网目录为准，不被选课社区覆盖
        try:
            t.update(scholar_client.enrich_teacher(t))
        except Exception as e:
            print(f"  [scholar] {t['name']}: {type(e).__name__}")
        faculty_crawler.classify(t)
        if (i + 1) % 50 == 0:
            print(f"  ... 已处理 {i + 1}/{len(all_teachers)}")

    print("== 写入 SQLite（重建，仅保留五个目标学院）==")
    conn = db.reset()
    db.save_teachers(conn, all_teachers)
    conn.close()

    conn = db.connect()
    n = conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
    n_adv = conn.execute("SELECT COUNT(*) FROM teachers WHERE is_advisor=1").fetchone()[0]
    n_cc = conn.execute("SELECT COUNT(*) FROM teachers WHERE course_community_id IS NOT NULL").fetchone()[0]
    n_sch = conn.execute("SELECT COUNT(*) FROM teachers WHERE scholar_id IS NOT NULL").fetchone()[0]
    n_course = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    n_paper = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    n_bio = conn.execute("SELECT COUNT(*) FROM teachers WHERE bio IS NOT NULL AND bio NOT IN ('','暂无内容')").fetchone()[0]
    n_hon = conn.execute("SELECT COUNT(*) FROM teachers WHERE honors NOT IN ('[]','') AND honors IS NOT NULL").fetchone()[0]
    conn.close()
    print(f"完成：教师 {n}（导师 {n_adv}），选课社区 {n_cc}，scholar {n_sch}，"
          f"课程 {n_course}，论文 {n_paper}，简介 {n_bio}，人才称号 {n_hon}")
    print("学院分布：")
    conn = db.connect()
    for r in conn.execute("SELECT college, COUNT(*) n FROM teachers GROUP BY college ORDER BY n DESC"):
        print(f"  {r[0] or '(空)':18s} {r[1]}")
    conn.close()
    print(f"数据库：{config.DB_PATH}")


if __name__ == "__main__":
    main()
