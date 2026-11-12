# 01-feedstitch（信汇）

Feedstitch — 多源目录/价目 Feed 归并落库：解析 → 业务键去重/冲突隔离 → 按源水位线增量或全量落库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5100 |
| API | http://localhost:10100 |

## 主链

配置源与夹具 → 触发 Run → 解析 / 去重 / 冲突隔离 → Canonical + 运行报告对账

## 种子说明

- **Alpha Catalog（clean）**：JSON，三件干净货号，增量可落库。
- **Beta Offers（dirty）**：JSONL，含与 Alpha 同键但价格不同的冲突行，以及迟到低 revision 行（底座增量会因水位线跳过）。
- **Gamma Shelf（xml）**：简易 XML，两件独立货号。

打开“运行台”选源跑一次增量，再看 Staging / 冲突 / Canonical 三页计数是否与本次 Run 报告一致。

## 类目指标集市（category_metric_mart）

“指标集市”页基于**当前有效 Canonical 主数据**实时聚合，不缓存手工数；点击“一键刷新指标”会重建整批类目指标并落库（表 `category_metrics`，批次表 `metric_refresh_runs`），刷新可重复执行，主数据变化后再次刷新即反映新口径，并会提示旧批次已过期。

口径（全部仅来自 `canonical_items`，与主数据列表同源）：

| 指标 | 口径 |
| --- | --- |
| 件数 item_count | `COUNT(*)`，各类目 Canonical 货号件数 |
| 价格合计 price_total | `SUM(price)` |
| 均价 price_avg | `AVG(price)`（= 价格合计 / 件数） |
| 最低价 / 最高价 | `MIN(price)` / `MAX(price)` |
| 件数占比 count_share | 类目件数 / 主数据总件数 |

每个刷新批次的报告含三项对账：各类目件数之和 = 主数据总件数、指标行数 = 主数据去重类目数、各类目价格合计之和 = 主数据价格合计；前端报告区逐项展示 PASS/FAIL。API：`GET /api/metric-mart`、`POST /api/metric-mart/refresh`、`GET /api/metric-mart/runs`。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现）

`lookback_backfill` / `schema_drift_guard` / `dead_letter_replay` / `webhook_push_source` /
`source_authority_rank` / `tombstone_retire` / `scd2_history` / `watermark_commit_gate` /
`field_map_transform` / `lineage_provenance` /
`fixture_dir_harvest` / `bronze_silver_promote` / `pii_mask_export` /
`rpa_form_queue`
