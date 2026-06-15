# Changelog

All notable changes to World Cup 2026 Schedule Aggregator.

## [1.0.0] - 2026-06-15

### Added
- **Phase 1**: SQLite 数据建模与表结构设计 (`init_db.py`)
- **Phase 2**: 采集器集成，引入 scrapling StealthyFetcher (`scrape_and_store.py`)
- **Phase 3**: 前端展示层开发，HTML/CSS/JS 多页面体系
- **Phase 4**: 暗色主题、国旗图片、UTC 前端时区转换
- **Phase 5**: 一键执行脚本 `Setup-WorldCup.ps1`
- **Phase 6**: 球队百科/教练档案 + 球员 Wikipedia 档案集成
- **Phase 7**: 小组积分榜、淘汰赛晋级树、射手榜三大视图
- **Phase 8**: Client-Server 架构重构（Flask API + 动态 Fetch 渲染）
- **Phase 9**: 接入 worldcup26.ir 真实 API 数据源
- **Phase 10**: 射手榜真实数据接入（17 位进球者）
- **Phase 11**: 球员详细信息补充 + 转播链接
- **Phase 12**: 冠军概率模型（ELO + 赛会表现 + Softmax）
- **Phase 13**: 48 队完整阵容入库（1,259 名球员）
- **Phase 14**: 历届冠军页面（2002-2022，含金球奖/金靴奖）
- **Phase 15**: ELO 替代方案参数调优
- **Phase 16**: 球员实力评分系统（0-100 分）

### Changed
- API 凭证移出代码，改为 .env 配置
- Cleanup: 删除 deprecated/ 目录和孤立 HTML 文件
- 清理 scrape_and_store.py 冗余代码
- 修复 Start-WorldCupServer.ps1 可移植性

### Project
- 源码目录重构为 `src/` 集中式结构
- 创建 README.md / LICENSE / CHANGELOG.md
