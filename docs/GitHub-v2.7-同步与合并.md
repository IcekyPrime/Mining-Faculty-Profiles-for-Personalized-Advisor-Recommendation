# GitHub v2.7 同步与改进版合并

生成时间：2026-11-23
上游仓库：`IcekyPrime/Mining-Faculty-Profiles-for-Personalized-Advisor-Recommendation`
干净副本：`.../Mining-Faculty-Profiles-for-Personalized-Advisor-Recommendation`
改进版：`.../Mining-Faculty-Profiles-for-Personalized-Advisor-Recommendation-副本`

## 1. 结论摘要

- 干净副本已从上一轮的 `d294268` 镜像状态同步到上游最新 `5dd4950`（tag `v2.7`）。
- 上游 `d294268..5dd4950` 共 **12 个文件、约 +514/−19 行**；其中 `assistant/` 的英文/拼音教师定位、桌面聊天抽屉、移动端 v2.7 与论文补充脚本是主要新增能力。
- 改进版已合入上游独有功能，并保留本地的 AI 查询、联网补全、数据工坊、BM25F、score_v2、收藏对比等能力；没有用上游文件整包覆盖本地页面与数据库。
- 改进版路由从 **30 增至 37**（新增 7 个 `/api/chat/*`）；上游单文件 `app/app.py` 只有 **6 条路由**，本地是蓝图化多模块实现。
- 验证通过：`pytest tests` **98 项**通过；`ruff check app tests assistant scripts/supplement_papers.py` 通过；`chat.js`、`mobile-ai.js`、`i18n.js` 的 `node --check` 通过；桌面与移动端浏览器烟测通过。
- 本轮改动**尚未提交**；合并前工作区已有 83 项改动，合并后当前工作区共 92 项未提交改动。合并前备份为分支/tag `backup/pre-sync-20261123` / `backup-pre-sync-20261123`（`321ea57`）。

## 2. 同步基线

| 项目 | 干净副本（上游） | 改进版（本地） |
| --- | --- | --- |
| 分支/提交 | `main` / `5dd4950`，tag `v2.7` | `test` / `8102bfc` + 未提交改动 |
| 教师 | 773 | 773 |
| 论文 | 13,092 | 13,088（保留本地审计表，未覆盖） |
| 课程 | 1,663 | 1,663 |
| 数据库表 | 5 张业务表 | 7 张，多 `ai_enrichment_jobs`、`import_jobs` |
| 应用路由 | 6 条（单文件 `app/app.py`） | 38 条（v2.7 同步时 37，第三轮新增 `/api/mining`） |
| 移动端版本 | 2.7 / 18 | 2.7 / 18（已同步） |
| 移动静态数据 | 13,092 篇 | 13,092 篇（已同步） |

安全备份：

```text
branch backup/pre-sync-20261123 -> 321ea57
tag    backup-pre-sync-20261123 -> 321ea57
```

备份是用 `git stash create` 对当时全部工作区改动生成的快照；随后 `git reset` 只取消暂存，工作区内容未丢失。

## 3. 上游 v2.7 逐文件增量

| 文件 | 上游改动 | 处理方式 |
| --- | --- | --- |
| `README.md` / `README_zh.md` | 文档与架构说明 | 参考后改写本地 README，不整文件覆盖 |
| `assistant/agent.py` | `+18`：规划上下文加入 `resolved_teacher`；API 规划前先用本地检索解析姓名；工具无结果时回退 `get_teacher` | 复制并保留本地注入式改造 |
| `assistant/api.py` | `+15`：规则模式识别英文/拼音姓名与 `introduce / who is / profile` 等提示词；命中姓名且无主题词时把推荐/搜索意图改为教师意图 | 复制并保留本地 400 校验、注入配置 |
| `assistant/retrieval.py` | `+61`：读取 `teachers.name_pinyin`；新增 ASCII 归一化、正反拼音形式、`find_teacher_in_text()`、`resolve_teacher()`、`by_name()` 代理 | 复制并新增 `set_db_path()` |
| `data/db/mentor.db` | 二进制增大；上游 13,092 篇论文 | **不覆盖**，保留本地 7 张表与 13,088 篇 |
| `docs/system.png` | 新架构图 | 另存 `docs/upstream-v2.7-architecture.png` |
| `scripts/supplement_papers.py` | 新增 365 行，OpenAlex + Crossref 补代表性论文 | 复制；未在本地库执行 |
| `mobile/android/AndroidManifest.xml` | `2.7` / `18` | 已同步 |
| `mobile/build_apk.ps1` | `--version-code 18 --version-name 2.7` | 已同步，保留本地 `web_ai` 复制顺序 |
| `mobile/android/assets/www/data.js` | 上游最新导出，13,092 篇 | 已覆盖为 4,956,970 B |
| `mobile/android/assets/www/js/mobile-ai.js` | `+38`：`LOOKUP` 增加 `introduce/who is/about`；新增 `NAME_KEYS`、`asciiTokens`，`findNames` 支持英文姓名与正反拼音 | 在本地加固版上合入 |

上游 v2.7 的移动端文件本身已包含 v2.5/v2.6 的抽屉滚动复位、收起失焦、`lostpointercapture` 等触控修复；本轮增量主要是拼音/英文姓名回退与版本号。

## 4. 重复功能取舍

| 功能 | 上游实现 | 本地实现 | 取舍 |
| --- | --- | --- | --- |
| 聊天后端 | `assistant/` 10 个模块，独立设置/历史 | 无 | **整包新增**；再注入本地 DB 与统一配置，避免两套 Key |
| AI 配置 | `assistant/llm` 独立读取 `chat` 设置 | `app/ai_config.py` + `/api/ai/config` | 采用本地一份 `data/ai_config.json`；聊天通过 `llm.configure(loader,saver)` 读写同一份配置 |
| 桌面聊天界面 | `chat.js` + `chat.css` + 抽屉模板，`ai.*` 词条 | 已有 `ai-search.js` / `ai-settings.js` / 设置页 | **只新增聊天抽屉**，不覆盖本地 AI 查询卡与设置；i18n 改用 `chat.*` 命名空间，避免与 `ai.*` 冲突 |
| 移动 AI 助手 | 拼音检索、触控/焦点修复、内置 API 调用 | 已有加固版：URL 白名单、远程 HTTPS、本机端点免 Key、30 秒超时、Key 掩码、语言重翻译、`web_ai` 兜底 | **保留本地加固**，吸收上游拼音/英文姓名与触控修复；不整文件覆盖 |
| 聊天卡片数量 | `_cards()` 默认 4 | 正文可列 5 位教师 | 改为默认 **6**，修复“正文 5 人、卡片 4 张”的不一致 |
| 对话历史 | 独立 `chat.db` | 无 | 采用上游 `assistant/store.py`；默认 `%LOCALAPPDATA%\JiaWoDao\chat.db`，可用 `JIAOWODAO_HOME` 覆盖 |
| 论文补充脚本 | OpenAlex/Crossref 补论文 | 无 | 合入脚本，未执行；本地库结构与上游不同，直接运行前应先确认教师范围 |
| 数据库 | 13,092 篇 / 5 表 | 13,088 篇 / 7 表 | **保留本地库**；移动静态数据单独同步，避免覆盖 `import_jobs` / `ai_enrichment_jobs` |
| 移动端版本 | 2.7 / 18 | 1.9.1 / 11 | 升到 2.7 / 18，并同步资源 query 与构建脚本 |

## 5. 合入后的代码结构

### 5.1 后端

新增 `assistant/`：

```text
assistant/
├─ __init__.py
├─ agent.py      规划、工具调用、API/规则回退
├─ api.py        /api/chat/* 蓝图
├─ answer.py     规则回答与卡片
├─ llm.py        OpenAI 兼容客户端、配置注入
├─ nlu.py        意图与槽位
├─ rag.py        本地 BM25 索引 + 图扩展
├─ retrieval.py  教师检索、英文/拼音定位
├─ store.py      对话历史
└─ tools.py      arXiv / Crossref / 官网 / Acemap 入口
```

本地改造点：

- `assistant/llm.py`：新增 `configure(loader, saver)`；支持本地端点无 Key；`status()` 增加 `local_endpoint`；`chat()` 仅在有 Key 时发 `Authorization`；`test_connection()` / `enhance()` 同步支持本地端点。
- `assistant/retrieval.py`：新增 `set_db_path(path)`，让助手复用应用工厂当前数据库并清缓存。
- `assistant/api.py`：`register_chat(app, db_path=None, settings_loader=None, settings_saver=None)`；`/api/chat/settings` POST 捕获 `ValueError` 返回 400。
- `assistant/answer.py`：`_cards()` 默认上限 6。
- `app/__init__.py`：注册 `assistant` 蓝图；`_load_chat_settings()` / `_save_chat_settings()` 在 `ai_config.load_config()` 与 `api_config.save_config()` 之间做字段映射（`base_url/model/api_key/enabled`）。

### 5.2 桌面端

- 新增 `app/static/js/chat.js`（14,253 B）与 `app/static/css/chat.css`（6,835 B / 293 行）。
- `app/templates/index.html` 在 `</main>` 后插入 `#ai-sheet` 抽屉；资源 query 使用 `20261123v27`。
- `i18n.js` 新增 `chat.*` 中英词条，`applyI18n()` 末尾调用 `window.ChatUI.refresh()`；原有 `ai.*` 留给 AI 查询卡。
- `chat.css` 增加 `#main { padding-bottom: 112px; }`，避免固定抽屉遮住页面底部内容。

### 5.3 移动端

- `mobile-ai.js` 合入 `NAME_KEYS`、`asciiTokens()`、`findNames()` 拼音回退；`LOOKUP` 增加 `introduce/who is/about`。
- 保留本地 143 行加固增量：`safeHttpUrl()`、`isLocalEndpoint()`、无 Key 本机端点、30 秒 `AbortController`、Key 掩码、语言切换重翻译、`web_ai` 兜底。
- `data.js` 更新为上游 v2.7 导出：4,956,970 B / 13,092 篇。
- `AndroidManifest.xml` 与 `build_apk.ps1` 升到 `versionCode 18` / `versionName 2.7`。

### 5.4 测试与脚本

- 新增 `tests/test_chat_api.py`：路由、状态、规则推荐卡片一致性、英文/拼音、统一配置、历史/清空。
- 新增 `tests/test_chat_ui.py`：抽屉 HTML、CSS/JS 接线、`chat.*` 命名空间、禁止残留 `t("ai.`。
- `tests/conftest.py` 新增 autouse `isolate_chat_store`，用临时 `JIAOWODAO_HOME` 隔离 `chat.db`。
- `tests/test_mobile_assets.py` 版本断言改为 2.7/18，新增拼音与触控修复静态断言。
- `scripts/supplement_papers.py` 已复制，支持 `--dry-run / --limit / --per-teacher / --no-openalex / --fix-years`。

## 6. 本地改进版独有的功能

以下功能在上游 `v2.7` 的 `app/app.py`（6 条路由）中不存在，属于本地改进版多出的能力：

| 功能 | 本地主要文件 | 说明 |
| --- | --- | --- |
| AI 自然语言查询 | `app/ai_api.py`、`app/ai_search.py`、`app/ai_client.py`、`app/static/js/ai-search.js` | `/api/ai/search`：模型解析需求为关键词/学院/职称/排序，再走本地检索并给推荐理由 |
| 联网补全教师档案 | `app/ai_api.py`、`app/ai_enrich.py`、`app/static/js/ai-enrich.js` | `/api/ai/enrich/preview|apply`、`/api/ai/jobs/<token>`；逐字段对比、默认只勾空值、事务写库、后台重跑处理层 |
| 数据工坊 | `app/import_api.py`、`import_engine.py`、`import_ai.py`、`import_store.py`、`app/templates/workspace.html`、`app/static/js/workspace.js` | CSV/JSON/XLSX 导入、规则清洗、质量报告、教师/论文/课程分类、重复检测、预览确认后事务入库 |
| AI/本地 Qwen 辅助清洗 | `app/import_ai.py` | 可选 OpenAI 兼容 API 或本地 Ollama/Qwen 复核，不生成缺失事实 |
| BM25F 检索排序 | `app/retrieval.py`、`app/api.py`、`app/static/js/directory-sort.js` | `sort=bm25`，姓名/拼音/关键词/方向/研究所/职称分字段加权；索引随数据库 mtime 失效 |
| 离线检索评估 | `scripts/evaluate_retrieval.py`、`docs/eval/queries.json`、`docs/eval/results.md` | NDCG@10 / MAP@10 / HitRate@10 / P@5 |
| 改进评分 v2 | `processing/score_v2.py`、`app/services.py`、前端 `score2` 排序 | 在保留原综合评分的同时提供第二套评分口径与排序 |
| 收藏与对比 | `app/static/js/shortlist.js`、`app.js`、`app/static/css` | 收藏 2–4 人并排比较综合评分/v2/h 指数/引用/论文/教学评分/完整度，可导出 CSV |
| 命令面板与检索体验 | `command-palette.js`、`search-suggest.js`、`highlight-hits.js`、`app-tabs.js` | `Ctrl/Cmd+K`、输入即补全、最近检索、命中高亮、URL 可分享检索状态 |
| 移动端安全加固 | `mobile/android/assets/www/js/mobile-ai.js` 等 | URL 协议白名单、远程 HTTPS、本机端点免 Key、30 秒超时、Key 掩码、语言重翻译、`web_ai` 兜底 |

补充说明：

- 上游也有中英双语、深浅主题、数据概况、教师档案、AI 助手；这些不算本地独有，未列入上表。
- 本地的 `score2` 只新增排序与展示，没有改动原 `score/score` 权重口径。
- 本地的导入与 AI 补全都保留“先预览、后确认、自动备份”的写库路径。

## 7. 验证记录

| 检查 | 结果 |
| --- | --- |
| `pytest tests` | 98 项通过 |
| `ruff check app tests assistant scripts/supplement_papers.py` | All checks passed |
| `node --check app/static/js/chat.js` | 0 |
| `node --check mobile/android/assets/www/js/mobile-ai.js` | 0 |
| `node --check app/static/js/i18n.js` | 0 |
| `/api/health` | 200，`version=2.7.0`，773 位教师 |
| 桌面 AI 抽屉 | 展开、推荐 5 位教师并显示 5 张卡、`yu yong` 定位俞勇、卡片跳档案成功 |
| 移动端 AI 抽屉 | 展开、`who is Yong Yu` 定位俞勇、建议 chips 与来源正常 |

未实测：

- 真实云端 API Key（本地无 Key，只验证 `rule` 模式与配置切换）。
- 本地 Ollama/Qwen 实际生成。
- Android APK 重新打包（本机无 Android SDK/JDK）。

## 8. 后续可选项

1. 需要把本地库补到 13,092 篇时，先备份 `data/db/mentor.db`，再按教师范围运行 `scripts/supplement_papers.py --dry-run`，确认后再去掉 `--dry-run`。
2. 需要发布时，在确认 92 项工作区改动后提交；备份分支/tag 可用于回滚。
3. 若要让桌面聊天与移动端共用云端 Key，可把手机端设置改为服务端代理，避免 Key 存在 WebView `localStorage`。
