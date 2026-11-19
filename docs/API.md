# HTTP 接口

基地址：`http://127.0.0.1:8765`（可用 `MENTOR_HOST` / `MENTOR_PORT` 覆盖）
所有接口返回 JSON，中文不转义；响应头带 `X-Response-Time-ms`，API 响应 `Cache-Control: no-store`，
超过 800 字节且客户端支持 gzip 时自动压缩。

## 错误格式

```json
{ "error": { "code": "invalid_param", "message": "参数 size 超出范围 [1, 100]" } }
```

| code | 状态码 | 含义 |
|---|---|---|
| `invalid_param` | 400 | 参数类型或范围不合法 |
| `invalid_sort` | 400 | 未知排序方式 |
| `not_found` | 404 | 资源不存在 |
| `method_not_allowed` | 405 | 方法不允许 |
| `internal_error` | 500 | 服务内部错误 |

## GET /api/health

健康检查。库不存在或损坏时 `status = "degraded"`。

```json
{
  "status": "ok",
  "teachers": 773,
  "db": { "file": "mentor.db", "exists": true, "size": 4816896, "updated_at": "2026-11-16T22:39:14" },
  "version": "1.1.0",
  "took_ms": 2.0
}
```

## GET /api/meta

前端启动时拉取的元信息。

```json
{
  "version": "1.1.0",
  "sorts": { "score": "综合评分", "academic": "学术能力", "teaching": "教学口碑", "relevance": "相关度" },
  "colleges": [{ "name": "计算机学院", "count": 243 }, "..."],
  "counts": { "teachers": 773, "papers": 13088, "courses": 1663, "phd_advisors": 151 },
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
| `q` | string | 空 | 姓名 / 拼音 / 关键词 / 研究方向 / 研究所 / 职称，多级匹配打分 |
| `college` | string | 空 | 学院精确筛选 |
| `sort` | enum | `score` | `score`（原始综合评分）/ `score2`（改进评分 v2）/ `academic` / `teaching` / `relevance` |
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
      "relevance": 0
    }
  ],
  "results": ["同上"]
}
```

## GET /api/teacher/<id>

| 字段 | 说明 |
|---|---|
| `courses` | 课程名、课程号、评分、评分人数、学期；按"有评分优先"排序 |
| `papers` | 被引最高的 20 篇：标题、发表处、年份、被引、作者 |
| `paper_total` | 本地收录篇数；`paper_count` 为 AMiner 统计的公开论文总数（可能不同，前端会分别说明） |
| `similar` | 关键词 Jaccard ≥ 0.25 的相似导师 |
| `collaborators` | 合作网络直接邻居（按合作次数排序，仅计算机学院有数据） |
| `cluster` / `community` | K-means 簇、Louvain 研究社区编号 |
| `pagerank` / `hits_authority` / `hits_hub` | 合作网络上的链接分析指标（无数据为 `null`） |
| `score_parts` | 五维分项：`{ "papers": {"value","pct","weight","used"}, ... }`，`honors` 额外带 `labels` |
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
| `colleges` | 学院与教师数，按人数倒序 |
| `coverage` | 9 个字段的覆盖率：`{field,label,count,total,ratio}` |
| `scores.histogram` | 10 档分布：`labels` / `original`(v1) / `improved`(v2) |
| `scores.top_improved` | 改进评分 Top 10，含 `score` 与 `score_v2` 对照 |
| `clusters` | K-means 簇：`id`、`size`、`keywords`、`members`（各 3 位代表） |
| `communities` / `community_count` | Louvain 社区人数（列出前 6） |
| `rules` | Apriori 规则：`antecedent`、`consequent`、`support`、`confidence`、`lift` |
| `db` | 库文件名与更新时间 |

```bash
curl "http://127.0.0.1:8765/api/insights"
```

## 前端直达链接

- 档案页：`/?teacher=401`、`/#/teacher/401`
- 档案页指定分区：`/?teacher=401&sub=academic`（`overview` / `academic` / `teaching` / `network`）
- 页面分区：`/?view=search`（默认）、`/?view=directory`、`/?view=insights`
- 设置抽屉：`/?view=settings`；旧链接 `/?view=about` 仍可用，会直接打开设置
- 检索状态：`/?q=人工智能&college=计算机学院&sort=teaching&page=2`；
  `q` 关键词、`college` 学院、`sort`（`score`/`score2`/`academic`/`teaching`/`relevance`）、
  `page` 页码。带 `q` 或 `college` 的链接会自动落到导师名录页；显式
  `view=insights` / `view=settings` 时不强制切页
- 快捷入口：`Ctrl / Cmd + K` 打开命令面板；收藏保存在
  `localStorage["mentor-favorites"]`，最近检索在
  `localStorage["mentor-recent-searches"]`

浏览器的前进/后退可用。
