# -*- coding: utf-8 -*-
"""文本处理单元测试：领域词保留、履历噪声被过滤。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "processing"))

import text_utils  # noqa: E402


def test_domain_term_kept_whole():
    tokens = text_utils.tokenize("主要研究计算机视觉与集成电路设计")
    assert "计算机视觉" in tokens
    assert "集成电路" in tokens


def test_career_noise_removed():
    text = "2010年毕业于上海交通大学，现任教于自动化系，承担国家自然科学基金项目"
    tokens = text_utils.tokenize(text)
    for noise in ("上海交通大学", "自动化系", "项目", "基金"):
        assert noise not in tokens


def test_clean_text_truncates():
    assert len(text_utils.clean_text("方" * 50, max_len=10)) == 10


def test_short_latin_filtered():
    tokens = text_utils.tokenize("AI ML OS 深度学习")
    assert "深度学习" in tokens
    assert "ai" not in tokens and "ml" not in tokens


def test_strip_career_keeps_directions_only():
    raw = "主要从事人工智能、模式识别与生物信息学的研究工作，曾获国家杰出青年科学基金，入选万人计划"
    kept = text_utils.strip_career(raw)
    assert "人工智能" in kept and "生物信息学" in kept
    assert "杰出青年" not in kept and "万人计划" not in kept


def test_strip_career_keeps_short_text_intact():
    raw = "研究方向：电力系统"
    assert text_utils.strip_career(raw) == raw
