"""数据层共享配置与常量。"""
import os

# 项目根目录（Project/）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
HOMEPAGE_DIR = os.path.join(RAW_DIR, "homepages")
DB_DIR = os.path.join(DATA_DIR, "db")
DB_PATH = os.path.join(DB_DIR, "mentor.db")

for _d in (DATA_DIR, RAW_DIR, HOMEPAGE_DIR, DB_DIR):
    os.makedirs(_d, exist_ok=True)

# 上海交通大学在 OpenAlex 中的机构 ID
SJTU_OPENALEX_ID = "I183067930"

# faculty.sjtu.edu.cn 学院 ID（电子信息与电气工程学院，即拆分前的电院，
# 覆盖 人工智能/计算机/自动化与感知/集成电路/电气工程 五个学院的主要师资）
COLLEGES = {
    1701: "电子信息与电气工程学院",
}

LIST_URL = (
    "https://faculty.sjtu.edu.cn/xyjs_list.jsp"
    "?urltype=tsites.CollegeTeacherList&wbtreeid=1001&st=0&id={college_id}&lang=zh_CN"
)
LIST_PAGE_URL = (
    "https://faculty.sjtu.edu.cn/xyjs_list.jsp"
    "?totalpage={totalpage}&PAGENUM={page}"
    "&urltype=tsites.CollegeTeacherList&wbtreeid=1001&st=0&id={college_id}&lang=zh_CN"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 教师（导师）职称白名单：这些职称通常具备招生资格
ADVISOR_TITLES = {
    "教授", "副教授", "研究员", "副研究员",
    "助理教授", "助理研究员", "特聘教授", "讲席教授",
    "长聘教授", "长聘副教授", "长聘助理教授",
    "首席研究员", "高级工程师", "教授级高工", "研究员级高工",
}

# 明确非导师（行政 / 教辅 / 实验）职称
NON_ADVISOR_TITLES = {
    "讲师", "助教", "工程师", "助理工程师", "实验师", "助理实验师",
    "馆员", "助理馆员", "辅导员", "秘书", "科员", "主任科员",
    "教务", "学工", "行政",
}

# 人才称号 / 身份 识别规则（按顺序匹配，命中即记录）
HONOR_PATTERNS = [
    ("院士", r"(中国科学?院|中国工程院|两院)?院士"),
    ("杰青", r"(国家)?杰出青年(科学基金)?|杰青"),
    ("优青", r"(国家)?优秀青年(科学基金)?|优青"),
    ("长江学者", r"长江学者(奖励计划)?(特聘教授|讲座教授|青年学者|青年项目)?"),
    ("海外高层次", r"海外高层次人才|千人计划|青年千人|青千"),
    ("万人计划", r"万人计划|青年拔尖"),
    ("国家级高层次人才", r"国家级高层次人才"),
    ("IEEE Fellow", r"IEEE\s*Fellow"),
    ("Fellow", r"(ACM|CCF|AAAS|OSA|SPIE)?\s*Fellow"),
    ("博导", r"博士(生)?导师|博导"),
    ("硕导", r"硕士(生)?导师|硕导"),
]
