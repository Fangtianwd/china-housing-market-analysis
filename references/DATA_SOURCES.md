---
name: housing-data-sources
description: 月度楼市分析任务使用的多源数据源清单和口径交叉验证方法
metadata:
  type: reference
  origin: coWork memory housing_data_sources.md（session 30572765-78ff-4975-b271-437e41f7ad23），2026-08-10 验证
---

月度楼市分析任务（skill `monthly-china-housing-market-analysis`）使用的多源数据源清单。
每次运行后如验证了新的源、发现新的失败模式或兜底方式，应更新本文件。

主源：
- 国家统计局"数据发布"RSS：https://www.stats.gov.cn/sj/zxfb/rss.xml
  优先条目：70个大中城市商品住宅销售价格变动情况、全国房地产市场基本情况、国民经济运行情况、房地产开发投资/固定资产投资。

补充源（用于多源交叉验证）：
- 中国人民银行 LPR 发布页：https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/3876551/index.html
  抓 1 年期和 5 年期以上 LPR 序列；5 年期 LPR 是房贷利率基准。
- 商业性个人住房贷款加权平均利率：https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/125838/5470606/index.html
- 金融机构信贷收支数据（住户贷款/中长期贷款）：调查统计司栏目 https://www.pbc.gov.cn/diaochatongjisi/116636/116756/index.html
- 货币供应量 M2 / 社会融资规模：https://www.pbc.gov.cn/diaochatongjisi/116636/116762/index.html 或调查统计司栏目
- 住建部首页及政策栏目：https://www.mohurd.gov.cn （首页可抓；子栏目用 WebSearch 兜底）
- 中国政府网政策：直抓 https://www.gov.cn/zhengce/ 经常 403，必须用 WebSearch 检索"国务院 房地产 通知 site:gov.cn" 作为兜底。
- 国家发改委价格监测：https://www.ndrc.gov.cn 用 WebSearch 检索。
- 第三方公开摘要（如可得）：中指研究院百城价格指数 https://industry.cih-index.com/ 、贝壳研究院 https://research.ke.com/ ，WebSearch 检索月度报告公开摘要做交叉验证。

口径交叉验证（重点三组）：
1. 销售口径：统计局"新建商品房销售额"同比 vs 央行"个人住房贷款新增"同比；方向相反时提示并分析原因（首付比例、提前还贷、利率切换等）。
2. 价格口径：统计局 70 城 vs 中指/贝壳研报公开摘要（若有）；无第三方时仅用统计局口径并说明限制。
3. 库存口径：统计局"待售面积" vs 住建部/地方库存；不可得时仅用统计局口径并说明限制。

已验证可访问性（2026-08-10 节点）：
- 国家统计局 RSS：HTTP 200，约 2.2MB XML。
- 央行 LPR 列表页和 LPR 详情页：HTTP 200，静态 HTML，正则可解析 "1年期LPR为3.0%，5年期以上LPR为3.5%"。
- 住建部首页：HTTP 200，HTML。
- 中国政府网政策库路径 https://www.gov.cn/zhengce/zhengceku/202405/ 返回 403；必须用 WebSearch 兜底。
