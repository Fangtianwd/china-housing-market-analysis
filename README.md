# china-housing-market-analysis

多源中国楼市数据分析 skill：从国家统计局、央行、住建部等官方源拉取数据，做多源交叉验证，生成交互式 HTML 看板、Excel、CSV 与 Markdown 中文报告。**专业与通俗并重**——既有统计口径严谨的分析层，也有面向普通读者的白话解读层。

迁移自 coWork skill `monthly-china-housing-market-analysis`；coWork 侧副本已停止维护，本仓库为唯一维护地。

## 结构

```
SKILL.md                    skill 主文档（agent 按此执行）
scripts/
  fetch_data.py             70 城价格指数查询（表1/2 总指数 + 表3/4 面积段分类指数）
  fetch_dev_stats.py        开发销售累计序列（投资/销售/待售/到位资金 + 分区）
  fetch_lpr.py              央行 LPR 全序列（2019-08 改革以来，支持离线模式）
  fetch_pbc.py              房贷加权平均利率季度序列（2024-Q3 起）
  fetch_archive.py          归档页回溯 RSS 窗口外的价格指数期次（2021-08 起）
  fetch_policies.py         住建部最新政策清单（首页快照 + 日期 + 关键词标签）
  validate_full_data.py     RSS 全量期次拉取 + 双解析器交叉校验 + 数据集元数据
  export_csv.py             全量数据集 → UTF-8 BOM CSV 明细
  history_store.py          增量历史库（按期次沉淀，修订留双版本）
  parsing.py                共享解析层（fetch_data / validate_full_data 共用）
  config.py / cache.py / exceptions.py
tests/                      unittest 测试（离线 fixture，零网络）
references/
  REFERENCE.md              70 城名单、指标说明、城市层级划分（固定）
  DATA_SOURCES.md           数据源清单与可访问性验证记录
  GLOSSARY.md               术语白话释义与直觉化换算规则（通俗层核心）
  KNOWN_BREAKS.md           口径断点登记表
artifacts/                  全量数据集、校验报告、增量历史库、LPR 序列、CSV、图表
agents/openai.yaml          agent 平台接入配置
```

## 快速开始

```bash
pip install -r requirements.txt        # 核心依赖（图表等可选依赖见 requirements-optional.txt）
python3 -m unittest discover -s tests  # 离线测试

# 单城查询（含面积段分类指数）
python3 scripts/fetch_data.py --city 武汉 --metrics 环比,同比,累计平均 --latest

# 例行全量采集（历史页永久磁盘缓存，重复运行很快）
python3 scripts/validate_full_data.py --dataset-output artifacts/full-dataset.json --report-output artifacts/validation-report.json
python3 scripts/history_store.py --from artifacts/full-dataset.json   # 沉淀增量历史库
python3 scripts/fetch_dev_stats.py --output artifacts/dev-stats.json  # 开发销售序列
python3 scripts/fetch_lpr.py --output artifacts/lpr-series.json       # LPR 全序列
python3 scripts/export_csv.py                                          # CSV 明细
```

## 设计理念

- **专业层**：双解析器交叉校验、口径断点登记、交叉验证量化规则（背离阈值、恒等式容差）、春节错位与基数效应处理规则、可复核的拐点识别规则。
- **通俗层**：每份交付物强制双层摘要（专业版 + 白话版）；术语首次出现必须带白话释义；指数变化必须附直觉化换算（100 万元的房子涨 3000 元）并声明边界；图表白话标题 + 100 分界线 + 红涨绿跌；固定免责与 70 城范围警示。
- **可维护性**：数据契约（统一中间文件 + series_id 命名）、完整性验收标准、失败处理路径、交付验收清单；磁盘缓存（历史页永久 + RSS 短 TTL）与增量历史库保证例行运行省时且不丢历史；已验证数据源与口径断点随仓库版本化。

## 路线图（已知待办）

已完成：

- ✅ 开发销售序列脚本化 `fetch_dev_stats.py`（只采官方累计口径，不做当月差分以避开"可比口径"回填陷阱）
- ✅ 增量历史库 `history_store.py`（按期次追加、修订留双版本；当前沉淀 2021-08 至今共 59 期）
- ✅ 磁盘缓存（历史公告页永久 + RSS 短 TTL，全量校验 7min -> 1.3min）
- ✅ 解析层去重 `parsing.py` + 测试加固（74 例离线全绿）
- ✅ 央行其余序列：房贷加权平均利率 `fetch_pbc.py`（2024-Q3 起；住户贷款/M2/社融栏目为动态页，按兜底规则 WebSearch）
- ✅ 归档页回溯 `fetch_archive.py`（2021-08 至 2023-12 共 29 期已入库）
- ✅ 政策清单结构化 `fetch_policies.py`（住建部首页快照 + 详情页日期 + 关键词标签）

剩余待办（按优先级）：

1. **2020-01 至 2021-07 价格指数补采**：超出归档覆盖，需 data.stats.gov.cn 在线查询接口或人工补采（见 KNOWN_BREAKS.md）。
2. **央行住户中长期贷款 / M2 / 社融序列**：现站点为 JS 动态页面，等待官方提供静态/接口渠道，或走 WebSearch 半自动。
3. 房贷加权利率更早历史（2024-Q3 之前）从货币政策执行报告补采。

贡献：每次运行 skill 后如发现新的数据源失败模式、口径断点或可复用脚本，分别更新 `references/DATA_SOURCES.md`、`references/KNOWN_BREAKS.md`、`scripts/`。
