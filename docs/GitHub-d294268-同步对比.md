# GitHub d294268 同步与改进版对比

生成时间：2026-11-21  
上游仓库：`https://github.com/IcekyPrime/Mining-Faculty-Profiles-for-Personalized-Advisor-Recommendation`  
上游最新提交：`d294268`（2026-11-21 11:57:21，提交信息 “Add AI assistant, mobile AI panel, and clean project structure”）

## 1. 同步结果

- 本地干净副本 `...-Recommendation` 已同步到 GitHub 最新内容。
- 由于 `git fetch` 连续被 `Connection was reset` 重置，本次改用 GitHub API 与归档下载，没有伪造远程仓库的 `origin/main`。
- 干净副本当前提交为 `5ae2ad6`，tag 为 `github-d294268`。
  - 该提交是“内容镜像提交”，内容与上游 `d294268` 一致，但 SHA 不是上游的 `d294268`。
  - `main` 比本地记录的 `origin/main` 领先 1 个提交，这是无法 fetch 造成的正常状态。
- 已对归档中的 90 个文件逐一做 SHA-256 校验，干净副本与归档 **0 差异**。
- 本次同步没有删除任何文件：上游 90 个文件，原干净副本 76 个文件，新增 14 个文件，均为 `assistant/`、`README_zh.md`、`chat.js`、`ai-settings.js`、`mobile-ai.js`。
- 改进版 `...-副本` **没有被覆盖，也没有合并上游代码**；本轮只新增了这份对比文档。

同步后的提交统计：

```text
29 files changed, 5979 insertions(+), 134 deletions(-)
```

## 2. 上游这次新增了什么

### 2.1 新增独立 AI 助手后端 `assistant/`（10 个模块，约 2,897 行）

| 模块 | 行数 | 作用 |
| --- | ---: | --- |
| `agent.py` | 402 | 让模型先规划意图、再选择本地/联网工具、最后总结 |
| `answer.py` | 584 | 规则模式下的回答模板、卡片、来源与建议问题 |
| `api.py` | 234 | `/api/chat/*` 路由、客户端 ID、Cookie 兜底、异常回退 |
| `llm.py` | 224 | OpenAI 兼容调用、服务端设置、连接测试 |
| `nlu.py` | 329 | 意图、槽位、教师名、学院、角色、追问上下文解析 |
| `rag.py` | 349 | 字段加权 BM25 + 合作网络/同研究所图扩展 |
| `retrieval.py` | 431 | 直接读取 `mentor.db`，不修改表结构 |
| `store.py` | 137 | 独立 `chat.db` 保存对话历史 |
| `tools.py` | 201 | 官方主页、arXiv、Crossref、Acemap 入口 |
| `__init__.py` | 6 | 包声明 |

上游只改了 `app/app.py` 末尾 9 行来挂载：

```python
from assistant.api import register_chat
register_chat(app)
```

因此它仍然是**单体 Flask app**，不是应用工厂。

### 2.2 新增 7 个对话接口

```text
GET  /api/chat/status
GET  /api/chat/settings
POST /api/chat/settings
POST /api/chat/test
GET  /api/chat/history
POST /api/chat
POST /api/chat/clear
```

关键行为：

- 客户端 ID 优先读 `X-Client-Id`，否则读 Cookie `jiaowodao_cid`。
- 对话历史写入独立 SQLite：Windows 为 `%LOCALAPPDATA%\JiaWoDao\chat.db`，其他系统为 `~/.jiaowodao/chat.db`。
- 设置写入 `%LOCALAPPDATA%\JiaWoDao\settings.json`，不写仓库目录。
- 没有 Key 时自动走规则回答；有 Key 时走“模型规划 + 工具调用 + 模型总结”。
- 对话历史在 `run_pipeline.py` 重建 `mentor.db` 时不会被清空，这是上游的一个明确设计优点。

### 2.3 桌面端新增 AI 对话抽屉

- `app/static/js/chat.js`：448 行，底部抽屉、拖动展开、历史消息、教师卡片、来源链接、建议 chips、清空对话。
- `app/static/js/ai-settings.js`：100 行，站点/模型/Key/连接测试，读 `/api/chat/settings`。
- `app/templates/index.html`：新增 `#ai-sheet` 抽屉、`#ai-messages`、`#ai-form`、`#ai-online`、设置里的 `ai-api-enabled` / `ai-api-model` 等。
- `app/static/css/style.css`：新增 332 行抽屉样式。
- `i18n.js`：新增 72 行 AI 词条。
- `app.js`：只新增 1 行，在语言刷新时调用 `ChatUI.refresh()`。

### 2.4 移动端

- 新增 `mobile/android/assets/www/js/mobile-ai.js`，1,205 行。
- 移动版本改为 `versionCode 16` / `versionName 2.5`。
- 新增 AI 抽屉的 HTML、CSS、i18n、`mobile-chrome.js` 返回键处理、`MainActivity` 的 `R.raw.web_ai` 映射、`build_apk.ps1` 的 `web_ai` 复制。
- 与旧版 APK 相比，上游移动端这次不只是加了一个面板，还修了抽屉的触控/焦点问题：
  - `lostpointercapture` 时收敛拖拽状态；
  - `setState()` 与拖动时复位 `sheet.scrollTop`；
  - 收起状态阻止输入框抢焦点，避免软键盘把抽屉顶栏顶出屏幕；
  - 键盘触发三角按钮时 `e.detail === 0` 的兼容处理。

### 2.5 文档

- `README.md` 大幅改写，并新增 `README_zh.md`。
- 明确说明：助手本地优先；可调用 arXiv、Crossref、Acemap、公开高校页面；不调用 OpenAlex；无 Key 走规则回答；设置与历史放在用户目录。
- **仍然没有任何模型清洗说明**，因为上游这次没有加模型清洗。

## 3. 仓库结构对比

### 3.1 接口数量

| 项目 | 路由数 | 说明 |
| --- | ---: | --- |
| GitHub `d294268` | 14 | 基础检索 + 7 个 `/api/chat/*` |
| 改进版 | 30 | 基础检索 + AI 查询/补全 + 数据工坊 + 健康检查 + 移动预览 |

两边共有 7 个基础路由：`/`、`/static/*`、`/api/search`、`/api/stats`、`/api/teacher/<id>`、`/api/colleges`、`/api/insights`。

- 上游独有：7 个 `/api/chat/*`。
- 改进版独有：23 个，包括 `/api/health`、`/api/meta`、`/api/ai/*`、`/api/import/*`、`/workspace`、`/import`、`/mobile/*`。

### 3.2 搜索排序

| 项目 | 支持排序 |
| --- | --- |
| GitHub `d294268` | `score`、`academic`、`teaching`、`relevance` |
| 改进版 | `score`、`score2`、`academic`、`teaching`、`relevance`、`bm25` |

上游 `assistant/rag.py` 内部也实现了 BM25，但它只服务对话，**没有暴露为 `/api/search?sort=bm25`，也没有离线评估**。改进版的 BM25 是可直接检索、可评估、可对比的独立排序。

### 3.3 应用架构

| 项目 | 架构 |
| --- | --- |
| GitHub `d294268` | `app/app.py` 单体 Flask，末尾 `register_chat(app)` |
| 改进版 | `app/__init__.py` 应用工厂 + 蓝图（api / ai_api / insights / import_api） |

这决定了两边不能整文件互换：

- 上游 `app/app.py` 会覆盖改进版的工厂入口；
- 上游 `app/__init__.py` 基本为空，不能替代改进版工厂；
- 上游 `app.js` 是旧版单文件逻辑，改进版已重写，不能直接覆盖；
- 上游 `style.css` 包含旧版布局，改进版已有独立的 `ai-features.css` 与 `workspace.css`，不能整文件覆盖。

## 4. 功能对比矩阵

| 能力 | GitHub `d294268` | 改进版 | 结论 |
| --- | --- | --- | --- |
| 本地教师检索 | 有，`retrieval.py` | 有，`services.py` | 两边都有；上游增加了对话场景的字段加权 |
| BM25 | 有，但只在 `assistant/rag.py` 内部 | 有，`/api/search?sort=bm25` + 离线评估 | 改进版可验证、可对比；上游不可直接评估 |
| 合作网络/同研究所图扩展 | 有，`rag.py` 图扩展 | 有合作网络图，但不用于检索扩展 | 上游的 Graph RAG 值得吸收 |
| 桌面多轮对话 | 有，底部抽屉 + 历史 + 建议问题 | 无多轮对话，只有单次 AI 查询卡 | 上游明显领先 |
| 对话中的教师卡/来源 | 有，卡片 4 张 + 来源链接 | AI 查询结果复用统一教师卡，无对话历史 | 上游交互更完整 |
| 对话工具调用 | 有，`agent.py` 可选择 6 种工具 | 无工具调用，只有一次解析 + 本地排序 | 上游是 Agent 架构，改进版是单步 RAG |
| arXiv / Crossref | 有，无 Key 公共 API | 无 | 上游独有 |
| Acemap | 只有人工检索链接，`link_only=True`，不抓数据 | 无 | 上游 README 的“调用 Acemap”说法偏宽 |
| 公开高校主页抓取 | 有，仅 `.edu.cn`，带 SSRF/大小/超时限制 | 有联网补全抓取，也有公网 URL 校验 | 两边都有；上游更偏学术来源 |
| Tavily / Serper 通用联网 | 无 | 有，`ai_enrich.py` | 改进版独有 |
| 网页证据 → 字段 diff → 预览 → 写库 | 无 | 有，`/api/ai/enrich/*` | 改进版独有 |
| 多轮上下文 | 有，`store.last_meta()` | 无 | 上游独有 |
| AI 设置存储 | `%LOCALAPPDATA%\JiaWoDao\settings.json` | `data/ai_config.json` | 上游更适合打包；改进版便于课程演示 |
| 设置密钥保护 | 服务端 `has_key/key_hint`，不回传 Key | 服务端 `public_config()`，不回传 Key | 两边都合格 |
| 本地端点免 Key | 不支持；`llm.chat()` 无 Key 直接报错 | 支持 Ollama/vLLM 本地端点 | 改进版更实用 |
| 模型辅助数据清洗 | 无 | 有，`import_ai.py`，可选 OpenAI 兼容/本机 Qwen | **改进版独有，上游没有模型清洗** |
| 手动导入 / 数据工坊 | 无 | 有，`/workspace`、`/import`、`/api/import/*` | 改进版独有 |
| 清洗质量报告 / 实体分类 / 重复检测 | 无 | 有 | 改进版独有 |
| 导入事务 / 备份 / 审计 | 无 | 有，`import_jobs` 表 | 改进版独有 |
| 移动 AI 抽屉 | 有，1,205 行，2.5/16 | 有，1,289 行，1.9.1/11，已加固 | 上游有触控修复；改进版有安全/兼容修复 |
| 移动端本机端点免 Key | 不支持 | 支持 | 改进版更实用 |
| 移动端 URL 协议白名单 | 无 | 有 `safeHttpUrl()` | 改进版更安全 |
| 移动端请求超时 | 无 | 有 30 秒 AbortController | 改进版更稳 |
| 移动端状态文案翻译 | 部分；切换语言可能残留 | 有 `refreshApiCopy()` 重新翻译 | 改进版更好 |
| 测试 | 0 个测试目录 | 13 个测试文件，89 passed | 改进版明显领先 |
| 文档 | README + README_zh | 大量 docs、截图、合并说明 | 改进版更完整 |
| 移动版本 | 2.5 / 16 | 1.9.1 / 11 | 改进版版本号落后 |

## 5. 关键模块逐项对比

### 5.1 桌面 AI：两套架构，不能直接互换

**GitHub `assistant/`：**

```text
用户问题
  → NLU/LLM 规划
  → 选择工具（search_teachers / get_teacher / get_lab /
             compare_teachers / list_college / search_online）
  → 本地 RAG（BM25 + 图扩展）或外部来源
  → 模型总结 + 教师卡 + 来源链接
  → 写入 chat.db 历史
```

特点：

- 支持多轮追问，“再推荐几位”“还有别的”会沿用上下文并排除已出现教师。
- 支持教师详情、实验室/同研究所、两位教师比较、学院名单、最新成果。
- 回答正文由工具结果约束，卡片和来源也从工具结果生成。
- 没有 Key 时退回规则模板，仍可用。
- 缺点：本地 Ollama 无 Key 也被判定为规则模式；Acemap 只是链接；卡片最多 4 张，但正文可能列 5 位，存在轻微不一致。

**改进版 `app/ai_*.py`：**

```text
用户问题
  → 模型解析（关键词 / 学院 / 职称 / 博导 / 排序）
  → 本地 SQLite 检索 + 既有 relevance/BM25
  → 模型写推荐理由
  → 返回统一教师卡
```

特点：

- 单次查询，不保留对话上下文。
- 解析结果结构化，直接驱动检索筛选与排序。
- 支持 `score2`、`bm25`，可与既有排序体系对齐。
- 另有 `ai_enrich.py`：Tavily/Serper 搜索 → 抓正文 → 模型抽取 → 字段 diff → 预览 → 确认写库 → 重跑处理层。
- 不支持 arXiv/Crossref/Acemap，也不支持“教师详情/实验室/比较”这类对话工具。

结论：

- 两者不是替代关系，而是互补关系。
- 上游负责“对话式检索与学术来源”，改进版负责“结构化检索 + 联网补全写库 + 数据工坊”。
- 最合理的路线是把上游 `assistant/` 作为**新增模块**挂进改进版工厂，而不是替换 `ai_*`。

### 5.2 桌面 UI：上游抽屉与改进版设置存在硬冲突

上游 `ai-settings.js` 直接依赖这些 ID：

```text
ai-api-enabled
ai-api-base
ai-api-model
ai-api-key
ai-api-save
ai-api-test
ai-api-status
```

改进版设置里实际是：

```text
ai-api-base
ai-api-key
ai-model
ai-web-provider
ai-search-key
ai-search-max
ai-web-enabled
ai-config-badge
```

冲突点：

- 改进版没有 `ai-api-enabled`，上游 `fill()` 第一行 `el.enabled.checked` 会直接报错。
- 改进版没有 `ai-api-model`，上游 `fill()` 的 `el.model.value` 也会报错。
- 上游设置只覆盖聊天模型；改进版设置还覆盖 Tavily/Serper、联网补全、最大结果数。
- 上游 `chat.js` 依赖 `#ai-sheet`、`#ai-messages` 等一整套 DOM，改进版没有这些节点。

因此：

- **不能**把上游 `ai-settings.js` 直接复制到改进版。
- **不能**把上游 `index.html` 整文件覆盖。
- 应新增独立的 `chat.js` + `chat.css` + 抽屉 HTML 片段；
- 聊天设置要么复用改进版 `/api/ai/config`，要么新增一个只读适配层，把上游 `/api/chat/settings` 映射到同一个配置源，避免用户看到两套 Key。

### 5.3 移动端：上游有触控修复，改进版有安全加固

逐文件差异（忽略 CRLF）：

| 文件 | 上游 → 改进版 |
| --- | --- |
| `mobile-ai.js` | +144 / -60；改进版 1,289 行，上游 1,205 行 |
| `mobile.css` | +1 / -0 |
| `index.html` | +15 / -14 |
| `i18n.js` | +24 / -10 |
| `app.js` | +1 / -0 |
| `mobile-chrome.js` | 完全一致 |
| `MainActivity.java` | +1 / -1，仅 `web_ai` 判断顺序 |
| `build_apk.ps1` | +3 / -3，复制顺序与版本号 |

改进版在移动 AI 上新增的能力：

- `safeHttpUrl()`：只允许 `http/https`，阻断 `javascript:` 等来源链接。
- `isLocalEndpoint()`：识别 localhost / 127.0.0.1 / ::1 / 10.0.2.2 / `.local`。
- 本地端点免 Key：`apiReady()` 允许本地端点无 Key。
- 30 秒 `AbortController` 超时。
- 请求头只在有 Key 时发送 `Authorization`。
- `apiKeyHint()` 短 Key 不再暴露前后缀。
- `setStatusKey()/refreshApiCopy()`：切换语言后重新翻译状态和占位符。
- 保存设置时校验 URL 协议、远程 HTTP 必须 HTTPS、远程端点必须有 Key。
- `undefined` 表示“没有调用 API”，`null` 表示“API 失败”，避免把失败误判成成功。
- 移动静态资源加 `?v=20261121ai6`，避免 WebView 缓存旧 JS。

但上游这次新增了改进版**没有**的触控/焦点修复：

- `lostpointercapture` → `onUp()`，避免拖拽状态残留。
- `setState()` 和 `onMove()` 中 `sheet.scrollTop = 0`，避免顶栏被内部滚动顶出屏幕。
- `peek` 状态下输入框获得焦点时自动 blur，避免软键盘把抽屉顶出可视区。
- 三角按钮键盘触发兼容。

这几项是移动端真机体验的关键，应该优先吸收。

### 5.4 数据工坊：改进版独有，必须保留

上游 `d294268` 仍然没有：

- `/api/import/*`
- `/workspace`
- `/import`
- `app/import_*.py`
- `import_jobs` 表
- 导入模板、质量报告、实体分类、重复检测、预览确认、事务入库、备份

改进版的数据工坊是完整闭环：

```text
上传 CSV/TSV/JSON/JSONL/XLSX
  → 解析与字段映射
  → 规则清洗
  → 质量报告
  → 实体分类
  → 重复检测
  → 预览确认
  → 事务入库 + 备份 + 审计
  → 可选模型复核（默认不生成缺失事实）
```

限制仍然是：25 MB、20,000 行、AI 最多 400 行、每批 8 行；冲突策略 `skip` / `update_empty` / `update_all`。

### 5.5 模型清洗：上游仍然没有

这一点需要明确区分：

- 上游新增的是**模型问答助手**，不是模型清洗。
- 上游 `processing/preprocess.py` 仍是规则清洗；
- 上游 `app/` 没有 `import_ai.py`，没有 `/api/import`，没有“模型复核导入字段”；
- 上游 `assistant/llm.py` 只负责“把检索结果组织成自然语言”，不写教师表。

改进版的 `app/import_ai.py` 才是模型辅助清洗：

- 默认规则清洗；
- 可选 OpenAI 兼容接口或本机 Qwen；
- 模型只做字段复核/纠错；
- 字段白名单；
- 不生成缺失事实；
- 不改原表结构，只新增审计表。

所以，**GitHub 最新版依然没有引入模型做数据清洗**；它的模型只用于对话和总结。

## 6. 改进版已经领先、无需向上游对齐的部分

- 数据工坊全链路与模型辅助清洗。
- `import_jobs` 审计、备份、事务入库、并发 `claim_apply()`。
- `score2` 与 BM25 暴露为可检索排序，并有离线评估。
- AI 联网补全：Tavily/Serper → 证据 → diff → 预览 → 写库 → 处理层刷新。
- 本机 Ollama/vLLM 端点免 Key（桌面 + 移动）。
- 移动端 URL 白名单、超时、Key 保护、语言重翻译、缓存版本号。
- 89 个测试与较完整的 docs/截图。
- `/api/health`、`/api/meta`、移动预览路由。
- 现有应用工厂与蓝图结构。

这些是改进版的核心增量，同步上游时不能为了“对齐”而删掉。

## 7. 仍建议从上游吸收的内容（按优先级）

### P0：移动端触控/焦点修复

只改 `mobile-ai.js`，不要整文件替换：

- 补回 `lostpointercapture`；
- 补回 `sheet.scrollTop = 0`；
- 补回 `peek` 状态输入框 focus guard；
- 保留现有 `safeHttpUrl`、`isLocalEndpoint`、30 秒超时、状态重翻译；
- 是否保留上游的 `thinking: { type: "disabled" }` 需要按实际 API 再验证，不要盲目加回。

### P1：把 `assistant/` 作为新增后端挂进改进版

建议：

- 复制 `assistant/` 到改进版根目录；
- 在 `create_app()` 里 `register_chat(app)`；
- 不改 `app/app.py` 单体入口；
- 不改现有 `/api/ai/*` 与 `/api/import/*`；
- 新增 `/api/chat/*` 路由测试。

风险点：

- 上游 `assistant` 直接读 `data/db/mentor.db`，与改进版同库，已验证最新版在改进版数据库上可返回 773 位教师、规则回答正常。
- 但上游 `assistant/llm.py` 的设置是独立 `settings.json`，与改进版 `data/ai_config.json` 不共享；需要做适配，否则用户要配两次 Key。

### P2：桌面聊天抽屉

- 新增独立 `chat.css`，不要改 `ai-features.css`；
- 新增抽屉 HTML 片段，不要整文件覆盖 `index.html`；
- 新增 `chat.js`，不要覆盖 `ai-search.js` / `ai-enrich.js`；
- 把 `chat.js` 的语言刷新接到改进版 `MentorI18n`，不要依赖上游 `renderDynamic()`；
- 解决 `ai-settings.js` ID 冲突：建议聊天设置复用改进版配置，不再单独做一套。

### P3：设置与历史存储策略

上游把设置和 `chat.db` 放在 `%LOCALAPPDATA%\JiaWoDao`，适合打包后安装目录只读的场景。改进版当前放在 `data/`，课程演示方便，但打包后可能不可写。

建议：

- 保留 `data/ai_config.json` 作为兼容回退；
- 新增“用户目录优先、仓库目录回退”的解析顺序；
- 对话历史单独放 `chat.db`，不要塞进 `mentor.db`，避免 `run_pipeline.py` 重建数据库时丢失。

### P4：版本号与文档

- 若吸收上游移动代码，版本应升到 `2.5` / `16`，而不是继续停留在 `1.9.1` / `11`；
- README 保留改进版的数据工坊与加固说明，不要把上游 README 整文件覆盖；
- 增加一节“上游 assistant 与改进版 ai_* 的关系”，避免后续维护者重复实现。

## 8. 不建议直接覆盖的文件清单

| 文件 | 原因 |
| --- | --- |
| `app/app.py` | 上游单体入口会破坏改进版工厂与蓝图 |
| `app/__init__.py` | 上游基本为空，不能替代应用工厂 |
| `app/static/js/app.js` | 改进版已完全重写，覆盖会丢失骨架屏、取消请求、图表复用、URL 状态等 |
| `app/static/js/ai-settings.js` | ID 与改进版不兼容，直接运行会空指针 |
| `app/static/css/style.css` | 上游旧布局样式会与改进版主题/布局冲突 |
| `app/templates/index.html` | 上游缺少数据工坊、AI 查询卡、设置联网配置等节点 |
| `app/static/js/i18n.js` | 上游词条较少，覆盖会丢失数据工坊与移动 AI 词条 |
| `mobile/android/assets/www/js/mobile-ai.js` | 会丢失安全加固、超时、本机端点、语言重翻译 |
| `mobile/build_apk.ps1` | 会退回 2.5/16 且丢失改进版构建顺序；应择机升级版本而不是回退 |
| `README.md` / `README_zh.md` | 会丢失数据工坊、89 测试、移动加固等说明 |

## 9. 建议合并顺序（本轮未执行）

1. **移动端 P0 修复**：在改进版 `mobile-ai.js` 中补触控/焦点修复，保留加固逻辑；`node --check` 通过。
2. **后端 assistant 挂载**：复制 `assistant/`，在工厂中 `register_chat(app)`；跑 `/api/chat/status` 与规则回答。
3. **配置适配**：让 `assistant/llm.py` 读取改进版统一配置，或提供只读映射；避免两套 Key。
4. **桌面抽屉**：新增 `chat.css`、抽屉 HTML、`chat.js`；语言切换接 `MentorI18n`。
5. **测试与验收**：新增聊天路由、无 Key 回退、Key 掩码、路由不冲突、移动静态接线测试；全量 `pytest`、`ruff`、`node --check`。
6. **版本与文档**：移动升到 2.5/16；README/docs 增加 assistant 说明。

验收标准：

- `/api/chat/status` 返回 773 位教师、`online_tools` 包含 official/arxiv/crossref/acemap；
- 无 Key 时 `/api/chat` 返回 `engine.mode=rule`，且教师卡/来源非空；
- 有 Key 时能走 `agent.run()`，失败自动回退规则；
- `/api/chat/settings` GET 不返回 Key 原文；
- 原有 `/api/ai/*`、`/api/import/*` 路由数量不减少；
- `pytest` 不少于 89 passed；
- 移动端抽屉展开/收起、返回键、软键盘、语言切换均正常；
- 真实云端 Key 与本地 Ollama 各验证一次。

## 10. 现场验证记录

已用改进版 `.venv` 启动干净副本（端口 8766）做只读烟测：

```text
GET /api/chat/status
→ engine.mode=rule, has_key=false, teachers=773
→ online_tools=["official","arxiv","crossref","acemap"]

POST /api/chat {"message":"我喜欢数据挖掘，推荐几位导师","lang":"zh"}
→ intent=recommend
→ cards=4
→ sources=5
→ engine.mode=rule
→ 正文列出 5 位教师
```

这证明：

- 上游 `assistant` 能直接读取改进版同一份 `mentor.db`；
- 无 Key 规则路径可用；
- 但“正文 5 位、卡片 4 张”存在轻微不一致，合并时应统一 `top_k` 与 `_cards()` 的上限。

另外确认：

- 上游 Acemap 只是 `link_only` 的人工检索入口，不是抓取 API；
- 上游桌面 LLM 无 Key 时不会尝试本地 Ollama；
- 上游没有测试目录；
- 上游移动版本是 2.5 / 16，改进版是 1.9.1 / 11。

## 11. 结论

这次 GitHub 更新不是“小修补”，而是新增了一整套**对话式导师检索 Agent**：

- 后端 `assistant/` 负责多轮对话、工具调用、BM25 + 图扩展、arXiv/Crossref/官网来源；
- 桌面端新增底部 AI 抽屉；
- 移动端新增 AI 面板并修复触控/焦点问题；
- 但它**仍然没有模型清洗、没有数据工坊、没有手动导入、没有 BM25 评估、没有移动端安全加固、没有测试**。

改进版目前领先的是“数据治理与可验证性”：

- 数据工坊、模型辅助清洗、事务入库、审计与备份；
- BM25 可检索可评估；
- AI 联网补全写库；
- 移动端安全与兼容加固；
- 89 个测试与完整文档。

因此正确策略不是二选一，而是：

> **保留改进版的数据工坊、BM25、AI 补全、移动加固与测试；把上游的 assistant 对话后端、桌面抽屉、移动触控修复选择性吸收进来；统一两套 AI 配置，避免双 Key。**

在未完成上述合并前，干净副本只作为“上游镜像”保留，改进版继续作为主工作副本，不应被覆盖。
