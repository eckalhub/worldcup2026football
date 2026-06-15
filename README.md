# World Cup 2026 Schedule Aggregator

世界杯 2026 赛程汇总系统 — 一个基于 Flask + Vanilla JS SPA 架构的赛程数据聚合与可视化平台。

## 功能特性

8 大核心视图，完整覆盖赛程生命周期：

| 视图 | 说明 |
|---|---|
| 赛事看板 | 即将开始 + 正在进行中的比赛，实时倒计时 |
| 全部比赛 | 所有比赛完整时间表 |
| 晋级树图 | 淘汰赛阶段对阵可视化 |
| 球队巡礼 | 48 支球队卡片网格展示 |
| 小组积分榜 | 12 个小组实时排名（胜/平/负/净胜球/积分） |
| 射手榜 | 按进球数排序的实时射手榜 |
| 夺冠热门 | 基于 ELO + 赛会表现的冠军概率模型 |
| 历届冠军 | 2002-2022 六届世界杯回顾 |

## 技术栈

- **后端**：Python 3.13 + Flask 3.1
- **数据库**：SQLite 3
- **前端**：Vanilla JavaScript SPA（无框架依赖）
- **样式**：暗色主题 CSS，赛博朋克风格
- **反爬**：Scrapling StealthyFetcher

## 数据来源

- [worldcup26.ir](https://worldcup26.ir) REST API — 实时比赛数据（JWT 认证）
- [TheSportsDB](https://www.thesportsdb.com) — 球员肖像、Fanart
- [Wikipedia REST API](https://en.wikipedia.org/api/rest_v1/) — 球员英文传记
- [sportshistori.com](https://sportshistori.com) — 48 队完整大名单数据

## 快速开始

### 前置条件

- Python 3.9+
- PowerShell（Windows）或 Bash（macOS/Linux）

### 方式一：快速启动（已有数据库）

```powershell
.\Start-WorldCupServer.ps1
```

自动安装依赖并启动 Flask 服务 → 访问 `http://127.0.0.1:5000`

### 方式二：首次搭建（无数据库）

```powershell
.\Setup-WorldCup.ps1
```

完整流水线：安装依赖 → 初始化数据库 → 数据抓取 → 启动服务

### 手动启动

```bash
# 安装依赖
pip install -r src/requirements.txt

# 初始化数据库
python src/init_db.py

# （可选）导入初始数据
python src/scrape_and_store.py --mode init

# 启动服务器
python src/app.py
```

### 环境变量配置

复制 `.env.example` 为 `.env`，填入 `worldcup26.ir` 的凭证（可选，用于 API 实时数据同步）：

```
WC2026_EMAIL=your_email@example.com
WC2026_PASSWORD=your_password
```

## 项目结构

```
project_root/
├── src/                        # 源代码目录
│   ├── app.py                  # Flask 服务入口
│   ├── data_adapter.py         # worldcup26.ir API 集成层
│   ├── data_service.py         # 数据查询与评分计算
│   ├── init_db.py              # SQLite 建表与迁移
│   ├── import_squads.py        # 48 队大名单导入器
│   ├── scrape_and_store.py     # 数据管道与调度
│   ├── requirements.txt        # Python 依赖
│   ├── power_ranking_data.json # ELO/FIFA/身价静态数据
│   ├── static/
│   │   ├── css/style.css       # 暗色主题样式
│   │   └── js/app.js           # SPA 前端逻辑
│   └── templates/
│       └── index.html          # SPA 入口模板
├── Start-WorldCupServer.ps1    # 快速启动脚本
├── Setup-WorldCup.ps1          # 首次搭建全流程脚本
├── .env.example                # 环境变量模板
├── .gitignore
├── LICENSE
├── README.md
└── CHANGELOG.md
```

运行时产物（不入库）：
- `worldcup2026.db` — SQLite 数据库
- `.wc2026_token.json` — API Token 缓存

## API 文档

| 端点 | 方法 | 说明 |
|---|---|---|
| `/` | GET | SPA 首页 |
| `/api/data` | GET | 所有核心数据（球队/球员/比赛/转播） |
| `/api/power_ranking` | GET | 48 队冠军概率排名 |
| `/api/player_ratings` | GET | 球员 0-100 能力评级 |
| `/api/trigger_scrape` | POST | 手动触发数据更新 |
| `/api/settings` | GET/POST | 读取/设置刷新间隔（1-60 分钟） |

## 冠军概率模型

采用 ELO 基线 + 渐进赛会表现的双层模型：

1. **ELO 基线**：转换为 0-10 标准化评分
2. **赛会表现加权**：随比赛进行，表现权重从 0% 线性增长至 65%
3. **Softmax 温度参数 T=2.5**：控制概率分布的离散度
4. **四级分层**：Elite / Contender / Dark Horse / Underdog

## 开源许可

[MIT License](LICENSE)
