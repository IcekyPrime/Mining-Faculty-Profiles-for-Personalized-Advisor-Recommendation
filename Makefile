# 常用任务入口（Windows 可用 Git Bash / WSL，或直接照抄 README 里的命令）
PY ?= python
VENV := .venv
ifeq ($(OS),Windows_NT)
PY := $(VENV)/Scripts/python.exe
endif

.PHONY: help venv install pipeline data quality serve test lint format clean eval

help:
	@echo "make install   创建 venv 并安装依赖"
	@echo "make pipeline  重跑处理层（关键词/相似/社区/聚类/关联/评分）"
	@echo "make data      把补录整合版并入数据库并重跑处理层"
	@echo "make quality   生成数据质量报告"
	@echo "make eval      运行 BM25 与规则相关度的离线评估"
	@echo "make serve     启动 Web 服务（默认 127.0.0.1:8765）"
	@echo "make test      运行 pytest"
	@echo "make lint      ruff 检查"

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements-dev.txt

pipeline:
	$(PY) processing/preprocess.py
	$(PY) processing/keyword_extract.py
	$(PY) processing/similarity_index.py
	$(PY) processing/ranking.py
	$(PY) processing/community.py
	$(PY) processing/clustering.py
	$(PY) processing/association.py
	$(PY) processing/score.py
	$(PY) processing/score_v2.py

data:
	$(PY) scripts/merge_authoritative_data.py --source "$(SOURCE)"
	$(MAKE) pipeline

quality:
	$(PY) scripts/data_quality_report.py

eval:
	$(PY) scripts/evaluate_retrieval.py

serve:
	$(PY) -m app.app

test:
	$(PY) -m pytest

lint:
	ruff check app processing scripts tests

format:
	ruff check --fix app processing scripts tests

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__
