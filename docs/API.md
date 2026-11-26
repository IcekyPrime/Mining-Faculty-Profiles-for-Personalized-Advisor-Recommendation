# HTTP 接口

基地址：`http://127.0.0.1:8765`（可用 `MENTOR_HOST` / `MENTOR_PORT` 覆盖）
所有接口返回 JSON，中文不转义；响应头带 `X-Request-ID`、`X-Response-Time-ms`、
`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: same-origin`。
API 响应 `Cache-Control: no-store`，超过 `MENTOR_GZIP_MIN_BYTES` 且客户端支持 gzip 时自动压缩。

非 API 路径的 404/405/413/500 返回 `app/templates/error.html` 的中文 HTML 页，页面上有同一个
`request_id`，便于对照服务日志；API 路径继续返回 JSON envelope。

## 错误格式

```json
{ "error": { "code": "invalid_param", "message": "参数 size 超出范围 [1, 100]", "request_id": "a1b2c3d4e5f6" } }
```

`request_id` 为每次请求生成的 12 位十六进制串，同时出现在响应头 `X-Request-ID`。

| code | 状态码 | 含义 |
|---|---|---|
| `invalid_param` | 400 | 参数类型或范围不合法 |
| `invalid_sort` | 400 | 未知排序方式 |
| `not_found` | 404 | 资源不存在 |
| `method_not_allowed` | 405 | 方法不允许 |
| `payload_too_large` | 413 | 上传文件超过 `MENTOR_MAX_UPLOAD_BYTES` |
| `internal_error` | 500 | 服务内部错误 |
| `ai_not_configured` | 400 | 未配置/未启用 AI 模型 |
| `search_not_configured` | 400 | 未配置联网搜索 |
| `ai_auth` / `search_auth` | 401 | 模型或搜索 Key 无效 |
| `ai_timeout` | 504 | AI 接口超时 |
| `search_empty` | 404 | 联网搜索没有结果 |
| `already_applied` | 409 | 补全任务已应用，不能重复提交 |

## GET /api/health

健康检查。库不存在或损坏时 `status = "degraded"`。

```json
{
  "status": "ok",
  "teachers": 773,
  "db": { "file": "mentor.db", "exists": true, "size": 4816896, "updated_at": "2026-11-16T22:39:14" },
  "version": "2.7.0",
  "took_ms": 2.0
}
```

## GET /api/meta

前端启动时拉取的元信息。

```json
{
  "version": "2.7.0",
  "sorts": { "score": "综合评分", "score2": "改进评分（v2）", "academic": "学术能力", "teaching": "教学口碑", "relevance": "相关度", "bm25": "BM25 检索", "topic": "主题相关度" },
  "colleges": [{ "name": "计算机学院", "count": 243 }, "..."],
  "counts": { "teachers": 773, "papers": 15083, "courses": 1663, "phd_advisors": 151 },
  "db_updated_at": "2026-11-16T22:39:14",
  "took_ms": 0.0
}
```

## GET /api/stats

统计卡片数据（含 h 指数直方图），字段与 v1.0 兼容。

## GET /api/colleges

`[{ "name": "计算机学院", "count": 243 }, ...]`

## GET /api/search

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `q` | string | 空 | 姓名 / 拼音 / 关键词 / 研究方向 / 研究所 / 职称，多级匹配打分；缩写别名来自 `data/mining/lexicon.json`，并从当前语料自动学习 |
| `college` | string | 空 | 学院精确筛选 |
| `sort` | enum | `score` | `score`（原始综合评分）/ `score2`（改进评分 v2）/ `academic` / `teaching` / `relevance` / `bm25`（BM25F，只召回词项命中的档案）/ `topic`（BM25 召回集内主题混合） |
| `page` | int | 1 | 1–10000 |
| `size` | int | 20 | 1–100 |
| `phd` | 0/1 | 0 | 只看博导 |
| `rated` | 0/1 | 0 | 只看有课程评分的教师 |

响应同时提供 `items` 与 `results` 两个相同的数组（兼容旧前端/脚本）：

```json
{
  "query": "操作系统", "college": "", "sort": "score", "page": 1, "size": 5,
  "total": 18, "pages": 4, "took_ms": 0.7,
  "items": [
    {
      "id": 3, "name": "陈海波", "name_pinyin": "chen haibo", "college": "计算机学院",
      "title": "教授", "institute": "并行与分布式系统研究所", "is_advisor": true,
      "is_phd_advisor": true, "research_directions": "...", "keywords": ["操作系统", "..."],
      "h_index": 34, "citation_count": 5000, "paper_count": 200,
      "honors": ["杰青", "..."], "rating": { "avg": 4.6, "count": 10 },
      "score": 80.4, "score_v2": 83.5, "score_coverage": 0.65,
      "relevance": 0, "bm25": 0,
      "topic": 0, "topic_similarity": 0,
      "topic_primary": 5, "topic_label": "机器学习/计算机视觉/人工智能"
    }
  ],
  "results": ["同上"]
}
```

`sort=topic` 时：`topic` 是 `0.6*BM25 + 0.4*主题相似度` 的混合分；`topic_similarity` 是纯主题余弦，
用于诊断。无主题模型或查询无主题词时，该排序退化为 BM25 次序。

## GET /api/teacher/<id>

| 字段 | 说明 |
|---|---|
| `courses` | 课程名、课程号、评分、评分人数、学期；按"有评分优先"排序 |
| `papers` | 被引最高的 20 篇：标题、发表处、年份、被引、作者 |
| `paper_total` | 本地收录篇数；`paper_count` 为 AMiner 统计的公开论文总数（可能不同，前端会分别说明） |
| `similar` | 关键词 Jaccard ≥ 0.25 的相似导师 |
| `collaborators` | 合作网络直接邻居（按合作次数排序，仅计算机学院有数据） |
| `cluster` / `community` | K-means 簇（自动 K）、Louvain 研究社区编号 |
| `topic_primary` / `topic_label` / `topic_distribution` | NMF 主主题、主题标签、教师-主题分布（`[{id,weight}]`） |
| `pagerank` / `hits_authority` / `hits_hub` | 合作网络上的链接分析指标（无数据为 `null`） |
| `score_parts` | 五维分项：`{ "papers": {"value","pct","weight","used"}, ... }`，`honors` 额外带 `labels` 与 `latest_year`（时效特征） |
| `honor_stats` | 荣誉时间线：`count`、`dated`、`dated_ratio`、`latest_year`、`recent_5y`、`categories`（talent/paper/teaching/competition/student/research_award/other） |
| `score_v2` | 改进版综合评分（缺失感知，与 `score` 并存对照） |
| `score_coverage` | 可用维度权重占比（0–1）；前端显示"数据完整度" |
| `radar` / `radar_known` | 雷达图百分位（缺失维度记 0）与"该维度是否有数据" |

示例：

```bash
curl "http://127.0.0.1:8765/api/teacher/401"
```

## GET /api/insights

数据洞察页的一次性聚合数据（只读，不写库）。字段：

| 字段 | 说明 |
|---|---|
| `total` | 教师总数，兼容旧前端 |
| `teaching` | 教学评分覆盖：`{filled,total,pct}` |
| `coverage` | 9 个字段的覆盖率：`{field,label,count,filled,total,ratio,pct}`（`filled/pct` 为旧版兼容字段） |
| `histogram` | 旧版评分分布：`bins` / `counts`（对应 v1 原始分） |
| `top` | 旧版原始综合分 Top 10 |
| `scores.histogram` | 10 档分布：`labels` / `original`(v1) / `improved`(v2) |
| `scores.top_improved` | 改进评分 Top 10，含 `score` 与 `score_v2` 对照 |
| `clusters` | K-means 簇：`id`、`size`、`keywords`、`members`（各 3 位代表） |
| `communities` / `community_count` | Louvain **研究相似社区**人数（列出前 6），含 `members/keywords/sample`；不是共同作者社区 |
| `rules` | Apriori 规则：`antecedent`、`consequent`、`support`、`confidence`、`lift` |
| `topics` | TF-IDF + NMF 主题模型：`method`、`k`、`document_count`、`vocabulary`、`items`（`id/label/terms`） |
| `db` | 库文件名与更新时间 |

```bash
curl "http://127.0.0.1:8765/api/insights"
```

## GET /api/mining

数据挖掘模型元信息（只读）。用于前端/课程演示展示“当前用了什么算法、模型规模多大”。

```json
{
  "method": "TF-IDF + NMF",
  "k": 8,
  "document_count": 771,
  "vocabulary": 1304,
  "topics": [{ "id": 0, "label": "智能/模型/机器人", "terms": ["智能", "..."] }],
  "lexicon": { "version": 1, "aliases": 26, "areas": 53, "path": "data/mining/lexicon.json" },
  "generated": true,
  "took_ms": 1.2
}
```

```bash
curl "http://127.0.0.1:8765/api/mining"
```

## AI 接口（v1.7）

所有 AI 接口都以 `POST` 接收 JSON；模型配置只保存在服务端 `data/ai_config.json`，
`GET /api/ai/config` 只返回 `has_api_key`，不返回密钥原文。

### GET /api/ai/config

返回 `enabled`、`api_base`、`model`、`has_api_key`、`configured`、`web_search` 与
`updated_at`。`configured=true` 表示 Base URL、模型名与 Key 都已具备。

### POST /api/ai/config

```json
{
  "enabled": true,
  "api_base": "https://api.openai.com/v1",
  "model": "gpt-4o-mini",
  "api_key": "sk-...",
  "web_search": {
    "enabled": true,
    "provider": "tavily",
    "api_key": "tvly-...",
    "max_results": 5
  }
}
```

`api_key` / `web_search.api_key` 留空表示保留旧值；显式清除传 `clear_api_key: true`。
启用 AI 时必须已有模型 Key、模型名与 Base URL。支持 `tavily`、`serper`、`none` 三种搜索提供方。

### POST /api/ai/test

用已保存配置做一次最小 Chat Completions 调用；若启用联网，再返回一次搜索条数。

### POST /api/ai/search

```json
{ "q": "想做医学图像、讲课口碑好的博导", "sort": "teaching", "page": 1, "size": 20 }
```

模型先把自然语言解析成 `{keywords, college, title, phd_only, sort, summary}`，再由本地
`search_corpus` 与 `relevance()` 执行候选检索；模型只生成整体说明与每位候选的
`ai_reason`，不会编造教师。响应中的 `items` 与 `results` 同义，`ai` 字段包含
`model`、`summary`、`keywords`、`filters`、`note`。

### POST /api/ai/enrich/preview

```json
{ "teacher_id": 401 }
```

搜索公开网页并让模型按证据抽取，返回 `token`、`diff`、`sources`、`confidence`。
`diff` 每项包含 `field`、`label`、`current`、`proposed`、`selected_default`、`confidence`、
`source`；默认只勾选原来为空的字段。没有可更新字段时 `token=null`。

### POST /api/ai/enrich/apply

```json
{ "token": "<preview token>", "fields": ["email", "homepage_url"] }
```

只写入暂存 diff 中的值，先备份数据库（`data/db/backup/mentor_before_ai_*.db`），
事务更新 `teachers` 选中字段，写入审计表，然后启动后台处理层刷新。返回
`status=running`、`backup`、`pipeline_status=queued`。

### GET /api/ai/jobs/&lt;token&gt;

返回补全任务状态与 `pipeline_steps`：每个步骤有 `name`、`label`、`status`、`output`。
`status` 依次为 `preview → running → done/failed`；`pipeline_status` 为
`queued → running → done/failed`。

### GET /api/ai/enrichments?teacher_id=401

返回最近的补全审计记录（不含完整 diff，便于列表展示）。

### 处理层刷新

联网补全应用后会依次运行：

```text
keyword_extract → similarity_index → ranking → community
→ clustering → association → score → score_v2
```

手动重跑：

```bash
python processing/refresh.py
python processing/refresh.py --from similarity_index
```

`refresh.py` 只更新处理列与 `data/exports/`，不会重建数据库；`MENTOR_DB_PATH` 可指向
其他数据库。

## 数据工坊：导入、清洗与分类入库

完整说明见 `docs/数据工坊-导入与清洗.md`。所有写库动作都必须先经过预览任务 token。

### GET /api/import/status

```json
{
  "ok": true,
  "ai": {
    "available": true,
    "model": "qwen2.5:7b",
    "api_base": "http://127.0.0.1:11434/v1",
    "local_endpoint": true,
    "has_api_key": false,
    "enabled": true
  },
  "limits": { "max_file_mb": 20, "max_rows": 20000, "max_ai_rows": 400 },
  "modes": ["auto", "course", "paper", "teacher"],
  "conflicts": ["skip", "update_all", "update_empty"]
}
```

本地 OpenAI 兼容端点（Ollama / vLLM / llama.cpp）允许不填 API Key；云端端点仍要求 Key。

### GET /api/import/template?type=teacher|paper|course

返回带 UTF-8 BOM 的 CSV 表头模板。

### POST /api/import/preview

`multipart/form-data`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `file` | file | CSV / TSV / JSON / JSONL / XLSX，≤25 MB、≤20,000 行 |
| `mode` | enum | `auto` / `teacher` / `paper` / `course` |
| `conflict` | enum | `skip` / `update_empty` / `update_all` |
| `ai` | bool | 是否立即尝试 AI 复核；失败时仍返回规则预览并带 `ai_warning` |

返回 `token`、`job`、`summary`、前 120 行 `rows`。**此接口不会写正式教师/论文/课程表**，只写 `import_jobs` 审计表与 `data/imports/<token>.json` 预览文件。

### POST /api/import/ai

```json
{ "token": "<preview token>", "mode": "auto" }
```

对已有预览分批调用模型；模型只能给实体类型、文本规范化和异常说明，`email/name/URL/年份/引用数` 等事实字段会被白名单丢弃。合并后重新执行规则校验。未配置模型返回 `400 ai_not_configured`，规则预览仍然有效。

### POST /api/import/apply

```json
{
  "token": "<preview token>",
  "conflict": "skip",
  "start_pipeline": true,
  "selected_rows": [1, 3, 5]
}
```

应用前用 SQLite backup API 生成 `data/backup/mentor_before_import_*.db`；`BEGIN IMMEDIATE` 事务写入，每行一个 SAVEPOINT。错误行不入库，重复行按冲突策略处理。`selected_rows` 必须是非空行号整数数组，省略表示全部可入库行；空数组、字符串、未出现的行号返回 `400`，不会退化为“写入全部”。写库权通过 `import_jobs` 的原子状态切换获取，两个并发请求只有一个能成功，其余返回 `409 already_applied`。没有任何插入/更新时不会排队处理层，`pipeline_status=idle`。

### GET /api/import/jobs

最近导入任务列表，默认 20 条，最多 100 条。

### GET /api/import/jobs/&lt;token&gt;

查询参数：`limit`（≤300）、`offset`、`status`（`all/ready/warning/error/duplicate`）、`entity`、`q`。
返回任务元数据、汇总、过滤后的总行数与当前页行。

### GET /api/import/jobs/&lt;token&gt;/export

导出清洗后的预览 CSV，含 `row_number/entity_type/status/quality`、清洗字段和 issues。

## 对话式导师助手（v2.7）

所有接口都支持 `X-Client-Id`（32 位十六进制）区分本机客户端；没有时使用/种下
`jiaowodao_cid` Cookie。设置与 `/api/ai/config` 共用同一份 `data/ai_config.json`，GET 不返回
Key 原文。

### GET /api/chat/status

返回 `engine`（`mode=rule|api`、`has_key`、`local_endpoint`）、`teachers` 与可用来源工具：
`official`、`arxiv`、`crossref`、`acemap`。

### GET /api/chat/settings / POST /api/chat/settings

读取/保存聊天模型设置。POST 字段与 `/api/ai/config` 对齐：`enabled`、`base_url`、`model`、
`api_key`（空表示保留旧 Key）、`clear_api_key`。保存后立即影响 `/api/ai/*` 与 `/api/chat`。

### POST /api/chat/test

发一条最小 `ping` 请求测试当前模型配置；不写入对话历史。本机端点无 Key 也可测试。

### POST /api/chat

```json
{"message":"介绍 yu yong","lang":"zh","online":false}
```

返回 `reply`、`intent`、`cards`（最多 6 张，与正文人数一致）、`sources`、`suggestions`、
`notes`、`engine`、`used_online`。支持中文姓名、英文姓名与正反拼音（如 `yu yong` / `Yong Yu`）。
本地检索同时索引姓名、方向、关键词、简介、论文与课程；当问题明确问“合作者/团队/实验室”时，
Graph RAG 会从词法命中的种子教师沿合作网络补充少量高权重邻居，并在卡片 `graph_reason` 中说明关系。
无 Key 或未启用模型时走本地规则；模型失败自动回退规则。

### GET /api/chat/history?limit=40 / POST /api/chat/clear

读取或清空当前客户端的对话历史。历史写入独立 `chat.db`（默认
`%LOCALAPPDATA%\JiaWoDao\chat.db`，可用 `JIAOWODAO_HOME` 覆盖），不随 `mentor.db` 重建丢失。

## 前端直达链接

- 档案页：`/?teacher=401`、`/#/teacher/401`
- 档案页指定分区：`/?teacher=401&sub=academic`（`overview` / `academic` / `teaching` / `network`）
- 页面分区：`/workspace`（数据工坊，也兼容 `/import`）、`/?view=search`（默认）、
  `/?view=directory`、`/?view=insights`
- 数据工坊任务恢复：`/workspace?job=<token>`；刷新/分享后自动加载对应预览与处理层状态
- 设置抽屉：`/?view=settings`；旧链接 `/?view=about` 仍可用，会直接打开设置
- 检索状态：`/?q=人工智能&college=计算机学院&sort=teaching&page=2`；
  `q` 关键词、`college` 学院、`sort`（`score`/`score2`/`academic`/`teaching`/`relevance`/`bm25`/`topic`）、
  `page` 页码。带 `q` 或 `college` 的链接会自动落到导师名录页；显式
  `view=insights` / `view=settings` 时不强制切页
- 快捷入口：`Ctrl / Cmd + K` 打开命令面板；收藏保存在
  `localStorage["mentor-favorites"]`，最近检索在
  `localStorage["mentor-recent-searches"]`

浏览器的前进/后退可用。
