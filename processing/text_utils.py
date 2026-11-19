# -*- coding: utf-8 -*-
"""处理层公共文本工具：领域词表、停用词、分词清洗。

关键词抽取与聚类共用同一套切词口径，避免两个脚本各写一份词表导致
「同一个词在一个环节是关键词、在另一个环节是噪声」。
"""
import re

import jieba

# 领域词表：保证「计算机视觉」这类复合词不会被切成两半
DOMAIN_TERMS = [
    "操作系统", "分布式系统", "系统软件", "虚拟化", "体系结构", "编译优化", "存储系统",
    "计算机视觉", "自然语言处理", "机器学习", "深度学习", "强化学习", "知识图谱", "大语言模型",
    "数据挖掘", "数据库", "计算机网络", "网络安全", "信息安全", "密码学", "隐私计算",
    "集成电路", "芯片设计", "微电子", "射频", "模拟电路", "数字电路", "半导体",
    "自动化", "控制理论", "机器人", "智能控制", "模式识别", "信号处理", "图像处理",
    "电力系统", "电力电子", "电机", "电气工程", "新能源", "智能电网", "高电压",
    "人工智能", "边缘计算", "物联网", "云计算", "区块链", "联邦学习", "图神经网络",
    "多智能体", "感知", "传感器", "信息融合", "无人系统", "脑机接口", "语音识别",
    "生物信息学", "生物医学工程", "数据科学", "大数据", "并行计算", "分布式计算",
    "智能交通", "智能制造", "信息安全", "计算机应用", "智能医学", "医学影像",
]

for _term in DOMAIN_TERMS:
    jieba.add_word(_term)

# 通用虚词 + 学术履历/机构词：简历字段（教育背景、任职经历、招生宣传）里的高频词
STOPWORDS = set("""
的 了 和 与 及 或 等 在 中 上 下 对 为 于 从 到 被 把 将 是 有 也 都 而 并 且 及其 以及
主要 研究 方向 领域 技术 方法 应用 系统 相关 基于 包括 从事 目前 负责 参与 进行 实现
提出 针对 开展 承担 主持 完成 获得 发表 论文 国际 国内 主席 委员 编委 教授 研究员
副教授 讲师 博士 硕士 学位 毕业 担任 荣获 获奖 一等奖 二等奖 三等奖 科学奖 技术奖
项目 课题 基金 合作 企业 成果 现任 曾任 期刊 会议 出版 国家 上海 教育部 学会 会员
杰出 优秀 人才 计划 学者 专家 作为 曾 曾获 其中 多 余 篇 次 名 位 引 引用
影响 产学研 产业 广泛 结合 产生 顶级 工作 基础 水平 重要 方面 情况 具有 通过 利用
采用 建立 形成 提高 促进 推动 支持 培养 团队 中心 实验室 学院 学校 大学 系 所
招生 联系 欢迎 同学 本科生 研究生 博士后 特聘 长聘 助理 任职 任教 本科 至今 年起
兼职 访问 奖励 期间 期间内 先后 分别 主要研究 兴趣 简介 个人 情况 信息 网站 主页
上海市 北京 中国 国家 省 部 主任 副主任 理事 委员 会长 秘书长 主席 首席 创始人
青年 中年 教学 工作 名誉 享受 政府 津贴 获得 承担 主持 参与 负责
学术 前沿 深度 计算 模型 理论 设备 手段 方式 课题 任务
出生 资助 使用 远超 差距 贡献奖 科技进步 发明奖 教学成果 论文奖
学习 研究成果 方向 领域内 交叉学科
委员会 大会 荣誉 超过 带领 实验 教育 杰出青年 长江学者 杰青 院士
上海交通大学 交通大学 电子信息 电气工程 自动化系 计算机系 研究所 重点实验室
工程研究中心 工程技术研究中心 协同创新中心 前沿科学中心
""".split())

# 常见会议/期刊缩写与英文虚词：避免论文标题把词表污染
ACRONYMS = {
    "acm", "ieee", "ccf", "sig", "sosp", "osdi", "eurosys", "asplos", "usenix", "vldb",
    "icml", "neurips", "nips", "cvpr", "iccv", "aaai", "ijcai", "acl", "emnlp", "iclr",
    "sigmod", "sigcomm", "tocs", "toc", "tcad", "tifs", "tdsc", "iot", "sigops", "sigarch",
    "atc", "fast", "nsdi", "mobi", "mobicom",
}
EN_STOP = {
    "and", "the", "for", "of", "in", "on", "with", "using", "based", "from", "to", "an",
    "is", "are", "was", "were", "university", "shanghai", "jiao", "tong", "systems",
    "system", "learning", "towards", "via", "by", "at", "their", "its", "his", "her",
    "our", "we", "as", "this", "that",
}


def clean_text(value, max_len=None):
    """统一空白与非法字符；可选截断，避免整段履历把研究方向淹没。"""
    text = re.sub(r"[\s\u3000]+", " ", value or "")
    text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9\+\- ]", "", text)
    text = text.strip()
    if max_len and len(text) > max_len:
        text = text[:max_len]
    return text


# 履历/获奖段落的起始标记：「主要从事 X、Y 的研究工作，曾获……」
CAREER_MARKERS = re.compile(
    r"(曾获|荣获|获得|入选|当选|获评|被评为|授予|担任|兼任|曾任|现任|先后|主持|承担|负责|"
    r"19\d{2}年|20\d{2}年)"
)


def strip_career(value):
    """截掉研究方向后面的履历/获奖清单，只留下真正的方向描述。"""
    text = value or ""
    match = CAREER_MARKERS.search(text)
    if match and match.start() >= 6:
        text = text[: match.start()]
    return text


def tokenize(text):
    """jieba 分词 + 停用词/缩写/纯数字过滤，返回小写词序列。"""
    out = []
    for word in jieba.lcut(text or ""):
        word = word.strip().lower()
        if len(word) < 2 or word in STOPWORDS:
            continue
        if re.fullmatch(r"\d+", word):
            continue
        if re.fullmatch(r"[a-z]+", word) and (len(word) <= 2 or word in ACRONYMS or word in EN_STOP):
            continue
        out.append(word)
    return out
