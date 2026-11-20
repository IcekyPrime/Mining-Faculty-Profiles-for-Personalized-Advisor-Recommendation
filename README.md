# Mining Faculty Profiles for Personalized Advisor Recommendation

交我导是一个导师检索与比较工具。项目爬取上海交通大学五个学院的公开教师信息，使用数据挖掘课程中的方法处理数据，提供桌面端应用和 Android 手机端应用。

<table>
<tr>
<td><img src="docs/system.png" width="620" alt="系统架构"></td>
<td>

数据层从学院官网、选课社区和学术 API 采集教师、论文、课程与评分数据，写入 SQLite。

处理层完成关键词抽取、相似检索、PageRank 与 HITS、Louvain 社区发现、K-means 聚类、Apriori 关联规则和综合评分。

应用层使用 Flask 提供接口，前端使用原生 HTML/CSS/JS 和 ECharts。桌面端由 pywebview 打开窗口，手机端使用 Android WebView。

</td>
</tr>
</table>

## 程序截图

桌面端：

<table>
<tr>
<td><img src="docs/front.png" alt="桌面端首页"></td>
<td><img src="docs/result.png" alt="桌面端教师详情"></td>
</tr>
</table>

手机端：

<table>
<tr>
<td><img src="docs/mobile-home.png" width="260" alt="手机端首页"></td>
<td><img src="docs/mobile-detail.png" width="260" alt="手机端教师详情"></td>
</tr>
</table>

## 功能

- 按姓名、拼音、研究方向、关键词检索教师。
- 按学院筛选。
- 四种排序：综合评分、学术能力、教学口碑、相关度。
- 教师详情页包含研究方向、简介、评分构成、联系方式、能力雷达图、合作网络、相似导师、课程和代表论文。
- 点击研究方向标签可以跳到相关教师。
- 支持浅色和深色主题，支持中文和英文界面。
- 手机端使用离线数据，不需要连接网络。

## 项目结构

```
Project/
├─ app/                       应用层
│  ├─ app.py                  Flask 接口
│  ├─ templates/index.html    页面
│  └─ static/                 样式、脚本、图片
├─ crawler/                   数据层
│  ├─ config.py               路径与规则
│  ├─ cs_crawler.py           计算机学院
│  ├─ college_crawler.py      其余四个学院
│  ├─ faculty_crawler.py      导师筛选
│  ├─ course_community.py     选课社区
│  ├─ openalex_client.py      OpenAlex
│  ├─ scholar_client.py       Semantic Scholar
│  ├─ arxiv_client.py         arXiv 作者列表
│  └─ crossref_client.py      Crossref 作者列表
├─ processing/                处理层
│  ├─ preprocess.py           清洗、拼音索引、合作网络
│  ├─ keyword_extract.py      jieba + TF-IDF
│  ├─ similarity_index.py     MinHash + LSH
│  ├─ ranking.py              PageRank + HITS
│  ├─ community.py            Louvain
│  ├─ clustering.py           K-means
│  ├─ association.py          Apriori
│  └─ score.py                综合评分
├─ mobile/                    手机端
│  ├─ android/                Android WebView 工程
│  ├─ tools/export_data.py    导出离线数据
│  └─ build_apk.ps1           APK 构建脚本
├─ data/
│  ├─ db/mentor.db            SQLite 数据库
│  └─ exports/                应用需要的导出文件
├─ docs/                      截图和架构图
├─ db.py                      数据库表结构
├─ run_pipeline.py            数据层入口
├─ launcher.py                桌面端入口
└─ environment/environment.yml
```

`data/raw/` 是爬取缓存，`.gitignore` 已忽略，克隆后不需要保留。

## 环境

Python 3.11。

```powershell
conda create -n dm-mentor python=3.11 -y
conda activate dm-mentor
pip install flask pywebview requests beautifulsoup4 lxml jieba pypinyin numpy pandas scikit-learn networkx mlxtend
```

## 运行桌面端

数据库和处理结果已经放在仓库中，可以直接运行。

```powershell
python launcher.py
```

调试时可以使用浏览器访问：

```powershell
python app/app.py
```

然后打开 http://127.0.0.1:8765

## 重新爬取和处理数据

```powershell
python run_pipeline.py
python run_pipeline.py --limit 50
```

选课社区需要账号，从环境变量读取，不要把账号写进代码：

```powershell
$env:COURSE_COMMUNITY_EMAIL = "你的邮箱"
$env:COURSE_COMMUNITY_PASSWORD = "你的密码"
```

处理层按以下顺序运行：

```powershell
cd processing
python preprocess.py
python keyword_extract.py
python similarity_index.py
python ranking.py
python community.py
python clustering.py
python association.py
python score.py
```

## 打包桌面端

```powershell
pyinstaller --noconfirm --onefile --windowed --name 交我导 --icon app.ico `
  --add-data "app/templates;app/templates" `
  --add-data "app/static;app/static" `
  --add-data "data/db/mentor.db;data/db" `
  --add-data "data/exports/collab_edges.csv;data/exports" `
  --add-data "data/exports/similar_pairs.json;data/exports" `
  --add-data "data/exports/association_rules.json;data/exports" `
  launcher.py
```

生成文件为 `dist/交我导.exe`。

如果启动时出现 ssl 相关错误，在命令中追加运行环境里的 DLL：

```powershell
  --add-binary "$env:CONDA_PREFIX\Library\bin\libssl-3-x64.dll;." `
  --add-binary "$env:CONDA_PREFIX\Library\bin\libcrypto-3-x64.dll;." `
  --add-binary "$env:CONDA_PREFIX\Library\bin\ffi.dll;." `
  --add-binary "$env:CONDA_PREFIX\Library\bin\liblzma.dll;." `
  --add-binary "$env:CONDA_PREFIX\Library\bin\libexpat.dll;." `
  --add-binary "$env:CONDA_PREFIX\Library\bin\libbz2.dll;."
```

## 手机端

手机端复用桌面端页面，数据导出到 `data.js` 后放进 Android 工程，由 WebView 离线加载。

构建前设置 Android SDK 和 JDK：

```powershell
$env:ANDROID_SDK_ROOT = "你的 Android SDK 路径"
$env:JAVA_HOME = "你的 JDK 路径"
```

导出数据并构建 APK：

```powershell
python mobile/tools/export_data.py
powershell -ExecutionPolicy Bypass -File mobile/build_apk.ps1
```

生成文件为 `mobile/dist/jiaowodao-mobile.apk`。

手机端使用 `https://appassets.androidplatform.net/assets/www/` 读取 APK 内的页面，读取顺序为 assets、res/raw、file://。状态栏和导航栏使用页面底色，顶部和底部保留空白。

## 数据和算法

数据来源：

- 上海交通大学五个学院的公开教师主页。
- 选课社区的公开课程评价。
- Semantic Scholar 和 OpenAlex 的论文与引用数据。
- arXiv 和 Crossref 的论文作者列表。

当前数据库包含 773 位教师、11093 篇论文、1663 门课程。

| 模块 | 方法 | 课程知识点 |
|---|---|---|
| preprocess.py | 拼音索引、作者抽取、合作网络 | 数据清洗与集成 |
| keyword_extract.py | jieba 分词 + TF-IDF | 文本特征抽取 |
| similarity_index.py | Shingling + MinHash + LSH | 相似项检索 |
| ranking.py | PageRank + HITS | 链接分析 |
| community.py | Louvain | 社区发现 |
| clustering.py | K-means | 聚类 |
| association.py | Apriori | 关联规则 |
| score.py | 多指标加权归一化 | 综合评分 |

处理结果：

- 关键词抽取 773 人。
- 相似导师 103 对。
- 合作网络 2347 条边、676 位教师。
- Louvain 20 个社区，模块度 0.678。
- K-means 8 个主题簇。
- 关联规则 11 条。
- 综合评分覆盖 773 人。

## 综合评分

```
score = (0.10 × 论文 + 0.20 × 引用 + 0.35 × 荣誉 + 0.25 × 教学) × 100
```

每项使用全库 5% 到 95% 分位归一化：

```
norm(x) = clip((x - P5) / (P95 - P5), 0, 1)
```

| 指标 | 权重 | 说明 |
|---|---|---|
| 论文 | 0.10 | 教师论文数 |
| 引用 | 0.20 | 教师总引用 |
| 荣誉 | 0.35 | 人才称号加权和，加职称基准 |
| 教学 | 0.25 | 课程评分按评分人数加权 |

有课程评分的教师为 498 人，平均分为 3.616。没有课程评分的 275 位教师使用这个平均分参与评分计算，教学评分仍显示 0，评分构成中的教学贡献用红色显示。

## 已知问题

- 研究方向缺 1 人，简介缺 14 人。
- 研究所缺 163 人，个人主页缺 216 人。
- 引用量缺 23 人，论文数缺 22 人，h 指数缺 5 人。
- 跨学院合作网络依赖作者姓名匹配，同名作者可能无法区分。
- 部分教师主页没有公开的获奖年份，荣誉只保留页面能确认的年份。

## 说明

项目数据来自公开网页和公开学术接口，只用于课程学习。爬取时请控制请求频率。仓库不包含账号、密码、cookie 或访问令牌。Release 页面提供打包好的桌面端和手机端程序。
