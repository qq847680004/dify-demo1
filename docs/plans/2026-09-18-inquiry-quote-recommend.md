# AI 报价推荐引擎 Implementation Plan

> **For agentic workers:** 按 Task 顺序逐步实施；实施时显式使用 `$dify-workflow-dsl` skill，并先查 `dify-docs` MCP。中英文冲突以英文原版为准。

**Goal:** 生成可导入 Dify 1.16 的 Workflow DSL：输入一张询价单的**已结构化**基础字段，外加可选 **补充信息**；召回前 LLM 判定进出口与运价类型、归一规格，并**解析补充信息**成国家/航线/船司/航线代码/直达中转/码头/船期；规则按各接口匹配方式填 Body（精确键 vs 检索句）；并行调用有效运价（不传 top，命中出齐规格价，合成时选最相似一档）、相似历史订单（`top` 只截订单条）、结算费用项（不传 top，目录用全部 `items[]`），召回后再由 LLM 合成可解释的报价草案 JSON（对齐 `docs/assets/询价管理-AI报价推荐引擎.png`，**不做竞品价参考**）。

**Architecture:** 单次运行的 `workflow`（非 Chatflow、非独立 Agent App、不用 Agent v2）。图结构：

```text
start → infer_route ────────────────────┐
start → need_supp → parse_supplement ───┼→ assemble
                 └→ empty_supp ─────────┘
assemble → search_rates | empty_rates
assemble → search_orders
assemble → list_charges
assemble → fetch_fx
(四路汇合) → pack_context → synthesize → normalize → end
```

运输方式用询价字典，不让模型改写。港码已能推出的进出口，assemble **覆盖**判定结果。补充信息抽出的船司/航线等按接口逻辑填：运价走有则精确，订单进检索句，费用项不收这些键。三个检索在键齐全时都要发生。报价合成仍在 `synthesize`（含规格价选档）。

**为何不是智能体：** 三个检索固定调用，不是运行时选工具。询价页要稳定 JSON。本仓用 `http-request`（禁止臆造跨工作区 OpenAPI `provider_id`）。对外产品名仍叫「AI 报价推荐引擎」。

**Tech Stack:** Dify App DSL `"0.7.0"`、`$dify-workflow-dsl`、`dify-docs` MCP、`scripts/validate_dsl.py`。HTTP 节点鉴权 Bearer + 自定义头 `TENANT-ID`；本地测试环境变量写入 DSL（见下表）。

**实施权威（只读这些）：** 本文件、`docs/assets/询价管理-AI报价推荐引擎.png`、实施时写入的 `docs/quote-recommend/CONTEXT.md`、Dify 节点以 `dify-docs` MCP + `$dify-workflow-dsl` 为准。

**禁止：** 打开 `digital-logistics` 询价 / AI 数据后端 Spec 当本 DSL 的字段或规则来源；接口 path、Body、出参、算费、`hint` 原文已写在本文件。本仓只交付 Workflow YAML，不改询价 Java、不写报价单。

---

## Global Constraints

- 目标：Dify 1.16.x / DSL `version: "0.7.0"`（必须加引号）
- 模式：`app.mode: workflow`；`app.name` = `AI 报价推荐引擎`
- 落盘：`dsl/workflows/inquiry_quote_recommend.yml`
- 节点 ID：仅字母、数字、下划线，长度 1–50
- 禁止写入 credential ID、MCP URL、私有 dataset ID；本地测试的 `AIDATA_*` 见下方环境变量表
- HTTP 基址 / Bearer / 租户用 `environment_variables`（本地测试已写入实值）
- LLM 即使关闭检索也必须带 `context: {enabled: false, variable_selector: []}`
- 召回前 `infer_route` 判定进出口、运价类型、不规范规格；`parse_supplement` 只抽补充信息里的精确线索；转换与 Body 只在 `assemble`（code）
- 模型不准手写货运类型码；不准用出口空运表冒充进口空运
- 补充信息未写明的船司/航线/国家/码头/中转一律留空，禁止编造；抽出的键不得推翻港码
- 交付前必须：`python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_recommend.yml`
- 导入后须重连模型凭据后再试跑；禁止声称「导入即可运行」
- 模型占位：`langgenius/tongyi/tongyi`；简单判定 `infer_route` / `parse_supplement` 用 `qwen3.7-flash-2026-07-15`（免费额度快照，能力同 Flash）；合成 `synthesize` 用 `qwen3.7-plus`（导入后重连）。Flash 抽取节点 `reasoning_mode` 用 `prompt`，避免通义插件在 `function_call` 时空 `content[]` 崩溃
- `dependencies` 原样抄 `inquiry_quote_extract.yml` 的 tongyi marketplace identity，禁止编造
- `competitorHint` 恒为 JSON `null`；禁止输出竞品价块
- 禁止调用结算 `billing_rule`；费用项接口只当目录；费用项 **不传 `top`**，`items[]` 全部当目录
- 运价检索 **不传 `top`**（默认 1）；报价只用 `hits[0]`，禁止从多条运价 hits 拼金额
- 运价空 hits **禁止**再发一次更松的检索；禁止拿掉港码做全库向量。必须精确空 → 补运价中心提示；有则精确回退时检索句必须仍含这些词
- 禁止因入参箱型截掉 `specPrices` 其它档；禁止把未匹配的关联费用种类当成漏报价
- 规格价选档：先精确代码，再同族近档；禁止跨种类（整箱↔特种↔拼箱↔空运）乱配；禁止默认用清单第一档
- 禁止把相似订单号写进费用来源句；禁止把历史金额在有运价时当报价；禁止汇率按 1 硬比
- 无进口空运 / 进口铁路主表：不得用 `AIR_EXPORT` / `RAIL` 冒充进口

---

## 范围

本仓只生成可导入的 Workflow。不读 inquiry 库、不写报价单、不改询价/AI 数据 Java。`result_json` 即对询价页的契约。

## 领域用语

不在本文件另造术语。询价：**询价单 / 报价草案 / 费用行 / 召回线索 / 运输方式 / 货品规格 / 补充信息**。AI 数据：**有效运价 / 相似历史单 / 费用项 / 进出口 / 运价类型 / 货运类型 / 检索句 / 规格价 / 费用种类 / 涨跌对照 / 市场运价涨跌**。本仓薄 glossary：`docs/quote-recommend/CONTEXT.md`。

---

## 输入契约（`start`）

报价需要的询价基础字段。**不要**收已定稿报价、订单、节点、权限开关。`inquiry_no` 仅回显，禁止写入三个检索 Body。

| 变量 | 类型 | 必填 | 对应详情 | 说明 |
| --- | --- | --- | --- | --- |
| `inquiry_no` | text | 否 | `inquiryNo` | 仅回显 |
| `customer_name` | text | 是 | `customerName` | 仅回显，不写入检索句 |
| `logistics_type` | text | 是 | `logisticsType` | 字典值 `AIR`/`SEA`/`RAIL`/`ROAD`/`MULTIMODAL`；兼容旧值 `SEA_FCL`/`SEA_LCL`/`EXPRESS` |
| `origin_port_code` | text | 是 | `originPortCode` | UN/LOCODE |
| `dest_port_code` | text | 是 | `destPortCode` | UN/LOCODE |
| `origin_port_name` | text | 是 | `originPortName` | 起运港名称 |
| `dest_port_name` | text | 是 | `destPortName` | 目的港名称 |
| `cargo_name` | text | 否 | `cargoName` | |
| `cargo_spec` | text | 否 | `cargoSpec` | 如 `2x40HQ`、`3CBM` |
| `quote_terms` | text | 否 | `quoteTerms` | 如 FOB/CIF；仅当港码推不出进出口时作判定信号，不得推翻港码 |
| `service_scope` | text | 否 | `serviceScope` | 如 到港 All-in；关键词可辅助 FBA/双清/驳船 |
| `urgency_level` | text | 否 | `urgencyLevel` | 不参与检索 |
| `supplement` | paragraph | 否 | 补充信息 | 业务员另填的自由文本（船司、航线、航线代码、国家、直达/中转、码头、船期等）。对应「请提供更详细的询价信息」通道 |

`max_length`：港码/类型 32，港名 128，规格/服务/品名 200，客户名 100，补充信息 1000。

询价基础字段没有码头、船司、航线名、航线代码、直达/中转、船期。这些**只从 `supplement` 抽出**；抽不出则 assemble **不编造**。抽出的键不得推翻已有港码，也不为运价补 `ioDirection`（运价类型已含进出口）。

---

## 判定与转换（`infer_route` / `parse_supplement` 判定，`assemble` 转换）

本方视角：**中国货代**。三个接口不是同一套枚举，也不是同一套入参：运价要 **运价类型** + 有则精确键；订单要 **进出口**（可选运输方式、货运类型），其余线索进检索句；费用项只要 **运输方式 + 进出口**，不收补充信息抽出的键。

### 补充信息解析（`parse_supplement`）

`need_supp`：`supplement` 去空白后非空才进 `parse_supplement`；否则 `empty_supp` 输出同名空串，不调 LLM。

`parse_supplement`：`parameter-extractor`，模型 `qwen3.7-flash-2026-07-15`，`reasoning_mode: prompt`，`temperature: 0.1`，关 thinking。只读 `supplement`（可带运输方式/规格作消歧，不得改写港码）。没写明的键必须空串，禁止猜测 MSC/直达/美国。

| 抽出字段 | 类型 | 何时有值 |
| --- | --- | --- |
| `carrier` | string | 船司/航司原文，如 MSC、马士基 |
| `route_name` | string | 航线名，如 美西 |
| `route_code` | string | 航线代码 |
| `country` | string | 目的国/国家原文，不擅自改 ISO |
| `transit_type` | string | 仅用户明确时：`直达` 或 `中转` |
| `origin_terminal` / `dest_terminal` | string | 起运/目的码头 |
| `schedule_note` | string | 船期/班期原文（**不是**精确键） |
| `spec_hint` | string | 补充信息里的规格线索（如「两个高柜」），可空 |

失败 `__is_success=false` 时所有抽出字段当空，assemble 仍用基础字段检索。

### 抽出字段填到哪（按接口逻辑，禁止三份 Body 套同一套键）

| 抽出 / 基础字段 | 运价（精确 vs 向量） | 相似历史单 | 费用项 |
| --- | --- | --- | --- |
| 港码 / 无码时港名 | **必须精确**（`originPortCode` 或 `originPortName`） | 港码精确；无码才填 `originPortName`；港名始终进检索句 | 不传 |
| 码头 | **必须精确**；有则填，无命中不改港 | 无码头键 → 进检索句 | 不传 |
| `carrier` / `routeName` / `routeCode` / `country` / `transitType` | **有则精确**（结构化 AND）**且必须写入 `queryText`**。第一轮空则丢掉这些结构化键，检索句里的原文留下做向量排序，同港同类型再出 1 条 | 无这些键 → 只进检索句做向量 | 不传 |
| 规格代码 / `containerTypes` | 提示，不滤行、不截价 | 可选 `containerType` 包含匹配（去掉 40HQ 默认值，未提取到箱型则不传）；规格仍进检索句 | 不传 |
| `schedule_note`、件数重量、补充信息剩余原文 | **仅检索句**（向量排序） | **仅检索句** | 不传 |
| `logisticsType` + `ioDirection` | 不靠它们选表 | 必填 io；物流类型可选 | **仅这两项** |

有船司却只写进检索句、不填运价 `carrier` → 禁止（第一轮精确命不中）。船期没有结构化列，禁止伪造 `transitType` 或 `validOn`。

丢掉有则精确键 = 只取消结构化 AND，**不是从 `queryText` 删词**。这五个键都能向量检索（语义文本含承运人/航线/航线代码/国家/中转），assemble **一开始**就写进检索句；第二轮才能在同港集合里按船司、航线排序，而不是变成无偏好的任意一条。

### 运价空结果：不准为凑命中再搜一遍

同一请求里已经是 **必须精确 AND + 有则精确 AND + 检索句只排序**。Dify **禁止**空 hits 后再发一次更松的运价 HTTP（尤其禁止拿掉港码/码头/运价类型去全库向量，会串港）。

| 空在哪 | 做什么 |
| --- | --- |
| 必须精确（运价类型、港码或无码地名、码头、有效日） | 该路就是没有当前有效运价。**不要**向量回退。询价已详细 → 用「请补充运价中心」hint；还缺港口/运输方式/箱型货量 → 用「请提供更详细的询价信息」hint。有历史单仍可按历史报价并声明仅供参考 |
| 有则精确（船司/航线/航线代码/国家/直达中转） | 丢掉全部有则精确**结构化键**，港口与运价类型不动；`queryText` **保留**这些原文。同港同类型再出 1 条（向量排序会偏向原船司/航线）。Dify 不二次调用。命中与入参不一致 → 当近似：`needVerify=true`，`hint` 追加「未命中指定船司/航线，已按同港有效运价报价，请核对。」**不要**因此改报空 |
| 一次调用后仍 `hits=[]` | 视为无有效运价，走上面必须精确空的 hint，不再自行向量重试 |

### 进出口 `ioDirection`

assemble **先**按港码规则，能推出则覆盖 `infer_route`：

| 条件 | 值 |
| --- | --- |
| 起运国家 = CN 且目的 ≠ CN | `1` 出口 |
| 目的国家 = CN 且起运 ≠ CN | `2` 进口 |
| 缺起运、目的非 CN | `1` 出口 |
| 缺起运、目的为 CN | `2` 进口 |
| 两端都 CN、都非 CN、或无法读国家 | 用 `infer_route`；仍空则 `1` 出口 |

条款/服务范围不得推翻港码已定方向。不得因「缺起运」把目的为中国港的单打成出口。

### `logisticsType`（规则，不经 LLM）

| 入参 | 归一（费用项 / 订单物流类型） |
| --- | --- |
| `AIR` / 空运 | `AIR` |
| `SEA` / `SEA_FCL` / `SEA_LCL` / 海运 | `SEA` |
| `RAIL` / 铁运 / 铁路 | `RAIL` |
| `ROAD` / `EXPRESS` / 汽运 | `ROAD` |
| `MULTIMODAL` / 多式联运 | `MULTIMODAL` |
| 无法识别 | 空 → 费用项不可调 |

货运类型（订单可选 `bizType`，能转则传；**禁止把运价类型写入订单**，`FCL_EXPORT` 等会 500「业务类型不支持」）：

| 运输方式 | 出口 `bizType` | 进口 `bizType` |
| --- | --- | --- |
| `AIR` | `AIR_EXPORT` | `AIR_IMPORT` |
| `SEA` | `SEA_EXPORT` | `SEA_IMPORT` |
| `RAIL` | `RAIL_EXPORT` | `RAIL_IMPORT` |
| `ROAD` | `TRUCK_EXPORT` | `TRUCK_IMPORT` |
| `MULTIMODAL` | `INTERMODAL`（无进出口拆分） | 同左 |

禁止 `FX_*` / 采购 / 仓储。模型不准手写这些码。费用项：汽运映射无进出口差异、多式联运映射「全部」，**仍必须传 `ioDirection`**。

### 运价类型 `rateType`（`infer_route` 判定，一次一张表）

**禁止**传 `SEA` 兼搜整箱+拼箱。`skip_rate=true` **仅当没有对应主表**（空运进口、汽运、多式联运、运输方式无法归一）。海运选不出整箱/拼箱 **仍走有效运价**，默认 `FCL_EXPORT`/`FCL_IMPORT`。

| 信号（规格 / 服务范围 / 运输方式 / 进出口） | rateType |
| --- | --- |
| 服务范围 FBA / 双清 / 集港 / 驳船 | `FBA` / `DUAL` / `PORT` / `FCL_FEEDER`（优先于普通整箱） |
| 特种 OT/FR/开顶/框架 + 出口 | `SPECIAL_EXPORT` |
| 冷冻 RF/reefer + 出口 | `REEFER_EXPORT` |
| 海运 + 出口 + 整箱箱型/FCL，或海运出口未写整箱/拼箱 | `FCL_EXPORT` |
| 海运 + 进口 + 整箱箱型/FCL，或海运进口未写整箱/拼箱 | `FCL_IMPORT` |
| 海运 + 出口 + CBM/TON/拼箱/LCL | `LCL_EXPORT` |
| 海运 + 进口 + 拼箱 | `LCL_IMPORT` |
| 空运 + 出口 | `AIR_EXPORT` |
| 空运 + 进口 | 无表 → skip_rate，不调接口 |
| 铁运 | `RAIL`（进口无独立表，仍只打 `RAIL`，不得改打空运） |
| 汽运 / 多式联运 | 无表 → skip_rate，不调接口 |

进出口推不出默认 `1` 出口。海运/铁运柜型读不出默认 `40HQ`、`quantity=1`，写入运价 Body `containerTypes`（只作提示）；`specGuessed=true`，主运行 `needVerify`，remark「规格按 40HQ 默认」。拼箱无 CBM/TON 仍打 LCL 表，选档单位默认 `CBM`，不编方数。空运出口不编重量档。**注意：相似案例接口去掉 40HQ 默认值，如果没有明确提取到箱型则不传 `containerType`，禁止把猜的 40HQ 塞给相似历史单接口导致误过滤。**

### 箱型 / 箱量

- 正则：`(\d+)\s*[x×]\s*(20GP|40GP|40HQ|45HQ|40NOR|20OT|40FR|20RF|40RF|…)` → `quantity` + `containerTypes`（多箱型全部进入）
- 仅箱型无数字 → `quantity=1`
- CBM/方/TON → 拼箱货量；空运重量档写入检索句，不编造柜型
- 正则失败但原文有规格含义 → 用 `infer_route` 归一
- 海运/铁运读不出柜型 → 运价默认 `40HQ` + 箱量 1（`specGuessed`）；拼箱无货量 → 单位 `CBM` 不编方数；空运不编重量档
- 运价 Body 的 `containerTypes` **只作提示**：不滤行、不截价；报价从出参 `specPrices` 选最相似一档
- 相似案例（历史订单）Body 的 `containerType`：**去掉 40HQ 默认值，只有实际提取到箱型才传；未提供/读不出箱型则不传该键**

### 检索句 `queryText`

规则按模板拼，禁止写金额、禁止写客户名；规格代码必须进句。有则精确五个键（`carrier` / `routeName` / `routeCode` / `country` / `transitType`）**只要抽出就写入检索句**，即使同时也填结构化精确键；第二轮丢掉结构化键后全靠这句做向量。船期与补充信息剩余原文只进检索句：

```text
{进出口中文}{运价类型中文或运输方式} {origin_port_name} {origin_port_code} {dest_port_name} {dest_port_code} {cargo_name} {cargo_spec} {carrier} {route_name} {route_code} {country} {transit_type} {schedule_note} {supplement去金额后的剩余}
```

例：`出口整箱 宁波 CNNGB 洛杉矶 USLAX 定制家具 2x40HQ MSC 美西 美国 直达 周班`

---

## 外部调用（本地测试环境变量已写入 DSL）

环境变量（本地测试，已写入 DSL `value`）：

| 名 | 类型 | 用途 | 本地测试值 |
| --- | --- | --- | --- |
| `AIDATA_BASE_URL` | string | 网关前缀 | `http://182.168.0.247:9999/aidata` |
| `AIDATA_API_KEY` | secret | `Authorization: Bearer`；Nacos `aidata.agent.api-key`，**不是**百炼 `aidata.embedding.api-key` | `aidata-agent-dev-20260920` |
| `AIDATA_TENANT_ID` | string | 头 `TENANT-ID` | `1` |

三个 Agent HTTP，条数各自约定：

| 节点 | 方法 | path | Body 要点 |
| --- | --- | --- | --- |
| `search_rates` | POST | `/agent/rate/search` | `queryText` + **必填 `rateType`** + 有代码列则精确港码，无代码列/无码则精确 `originPortName`/`destPortName` + 抽出则填码头/船司/航线/航线代码/国家/直达中转 + 可选 `containerTypes`/`validOn`；**不传 `top`**；禁止 `logisticsType` / `bizType` 选表；一般不传 `ioDirection`；禁止 `originPlace`/`destPlace` |
| `search_orders` | POST | `/agent/order/search` | `queryText`（含补充信息与船司航线船期）+ **必填 `ioDirection`** + `logisticsType` + 港码（无码才 `originPortName`/`destPortName`）+ 可选 `bizType`（货运类型：`SEA_EXPORT` 等，**不是** `FCL_EXPORT`）/`containerType`（仅实际有箱型才传，去掉 40HQ 默认值）；`top=8` 只截订单条；默认关闭 60；禁止 `rateType`；禁止把运价专用键塞进 Body；出参港名为 `originPortName`/`destPortName` |
| `list_charges` | POST | `/agent/settlement/charge-items` | **仅** `logisticsType` + `ioDirection`；**不传 `top`**；禁止港口、金额、`queryText`、船司航线国家。汽运/多式联运仍必须带进出口 |

运价精确键（有值才填，**禁止编造**）：

| 入参 | 匹配 | 本工作流 |
| --- | --- | --- |
| `rateType` | 必须精确（选表） | 必填 |
| `originPortCode` / `destPortCode` | 必须精确 | 有港码且该表有代码列则必填；填了无命中不改搜其它港 |
| `originPortName` / `destPortName` | 无港码时必须精确 | 仅当该端无港码、或该 `rateType` 主表无代码列（空运/进口整拼/铁路/特种/冷冻/FBA 等）才填；**有港码不要再 AND 港名**，港名只进检索句 |
| `originTerminal` / `destTerminal` | 必须精确 | 补充信息抽出才填；填了无命中不改搜其它码头 |
| `carrier` / `routeName` / `routeCode` / `country` / `transitType` | 有则精确；空则丢掉这些结构化键、同港同类型再出 1 条 | 抽出才填结构化键，**同时写入 `queryText`**。第二轮不从检索句删这些词 |
| `containerTypes` | 不滤行、不截价 | 可选提示；报价从 `specPrices` 选最相似一档 |
| `validOn` | 必须精确（日历） | 可空=当天；禁止用船期冒充 |
| `top` | 第一轮条数，默认 1 | **不传** |

HTTP 鉴权：Bearer API Key（`type: "api-key"` / `bearer`），另加头 `TENANT-ID`。JSON body。重试 2～3 次。失败走错误处理：**不中断**，该路空 hits/`items=[]`。

响应只读这些键（外层 `data`）：

- 运价 `hits[]`（默认至多 1 条）：`bizId`、`rateType`、`rateTypeLabel`、`carrier`、`originPortCode`、`destPortCode`、`originPortName`、`destPortName`、`routeName`、`routeCode`、`country`、`effectiveDate`、`expireDate`、`updateTime`、`containerTypes`、`currency`、`score`、**`specPrices[]`**（`spec`、`amount`、`currency`、`unit`；该行全部有价规格）、`extras[]`（`extraId`、`feeKind`、`feeKindLabel`、`feeName`、`unit`、`currency`、`specPrices[]`、`unitPrice`、`perBill`、`minAmount`）。`sell20gp`/`priceN`/`costCbm` 等便利字段可忽略，**以 `specPrices` 为完整清单**。JSON **无** `originPlace`/`destPlace`。
- 订单 `hits[]`：`bizNo`、`originPortCode`、`destPortCode`、`originPortName`、`destPortName`、`cargoName`、`cargoSpec`、`containerType`、`orderStatusLabel`、`updateTime`、`etd`、`score`、`fees[]`（该单全部已锁定行：`feeCode`、`feeName`、`feeDirection`、`currency`、`unit`、`quantity`、`unitPrice`、`amount`；**不被 `top` 截断**）
- 费用项：`businessTypeLabel` + `items[]` **全部**（`chargeCode`、`chargeName`、`defaultCurrency`、`defaultUnit`、`chargeNature`、`chargeType`）

**不调**（本轮）：`GET /agent/rate/types`、`GET /agent/*/record`、`GET /agent/sources`。

**公开汇率**（报价展示币默认 USD）：

- 主：`https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json`
- 主失败才备：`https://latest.currency-api.pages.dev/v1/currencies/usd.json`
- 都失败：不写涨跌、金额照报；禁止汇率=1；禁止因此写「无法对照」

`get_order_record` / `get_rate_record` 本轮不做。空运进口等 skip_rate 时 `empty_rates` 输出与成功空 hits 同形：`{"data":{"hits":[]}}`。

---

## 算费规则（写入 `synthesize` 系统提示；code 再兜底形状）

【匹配到的市场运价】【相似历史单】【费用明细】分别进 `marketRates` / `similarQuotes` / `fees`。【报价说明】及缺项句写入 `hint`。合计相对历史的上浮/下跌/持平另写 `trendHint`，颜色写 `alertColor`。**当匹配到相似历史单时，严禁提示“未匹配到足够相似的历史关闭单，故无上浮/下跌对照”，且必须计算并提供上浮/下跌标识（trendText、marketRates.trend）和提示语（trendHint、alertColor）。**

1. **有有效运价**：只用 `hits[0]`。主运费与 extras 都从该行 `specPrices[]` **选出最相似尽量精准的一档**（规则见下）。关联费用按 `feeKindLabel` 分种类，再按 `feeName` 对齐费用项；无规格价则用 `unitPrice`/`perBill`。未匹配种类没有行，不要当成漏报价。不同种类禁止合成一行。同一 `chargeCode`/规范化中文名禁止两行。禁止从多条运价 hits 拼金额。
2. **无运价有历史**：金额来自相似单 `fees[]`（`chargeCode`=`feeCode` 优先，其次规范化中文名），必须声明仅供参考。禁止同义词猜（THC ≠ 目的港操作费）。每条 hit 的 `fees[]` 全部列出。
3. **两边都有**：报价仍按这一条运价；侧边仍列出该条市场运价与全部相似单；每项一行涨跌。
4. **两边都无**（未调有效运价或 hits 空，且无历史）：`fees=[]`，hint 用「请补充运价中心的数据或联系管理员。」
5. 目录有、运价/历史都没有的项：可按目录名补一行，`sourceType=DIFY`，`needVerify=true`，`remark` 含「参考价格，请核实」，金额禁止臆造——无依据则 `unitPrice=0` 且 `selectedFlag=0`；`hint` 追加缺项句。费用项目录用 `items[]` 全部，不要只摘前几条。
6. 涨跌：每项一行；模型自选对照哪张历史单；相对差绝对值 ≥10% 为差距巨大；每一张都巨大则改对 top1。合计涨跌用同一张对照单，写入 `trendHint`（见下）。只比历史 **应收**（`feeDirection=1`）。先折同规格（单价×询价箱量 ↔ 历史同柜型金额）。币种不同先用 `fetch_fx` 再比；换汇后的涨跌句写出所用汇率与日期；换不到该项不写涨跌、金额照报。对不上费用名 → `历史无此项，无法对照`。不得因历史没有就删掉运价项。
7. All-in / 到港：`service_scope` 不发明「一口价」合并行；仍按费用项逐行报。
8. `quantity`：柜型费用解析出的箱量；票结（提单费等）用 `1`。
9. `sourceType`：运价主表/关联费用 `RATE`；历史 `HISTORY`；目录补缺 `DIFY`。不要 `MANUAL`。
10. 合计 `totalAmount`：只加 `selectedFlag=1` 且 `unitPrice>0` 的行；`totalCurrency` 优先运价币种，否则 `USD`。
11. **费用来源**（写入 `fees[].remark`；禁止写订单号）：
    - 运价主表规格：`来源=运价中心 {rateId} {rateTypeLabel} {spec}`
    - 运价关联费用：`来源=运价中心 {rateId} {feeKindLabel} {feeName} extraId={extraId}`
    - 历史：`来源=相似订单明细 {feeName} {amount}{currency}/{单位}`
12. **规格价选档**（主表与每条 extra 各自对 `specPrices[]`，对照 `cargo_spec` + `spec_hint` + 补充信息；写入 `analyzed.selectedSpec`）：
    1. 精确：规格代码全等（`40HQ`=`40HQ`，含「两个高柜」归一后的代码）
    2. 别名：高柜→`40HQ`，平柜→`40GP`，开顶→OT 族，框架→FR 族，冷冻→RF 族
    3. 同族近档（仅上一步没有时）：`40HQ`↔`40GP`↔`40NOR`；`20GP` 不升到 40；OT 不配 GP；拼箱在 `CBM`/`TON`/`MIN` 里按原文单位选，空则 `CBM`；空运按计费重靠最近重量档（`N`/`+45`/`+100`…），就近不跨到柜型
    4. 仍没有可对的同族 → 该行金额 0、`selectedFlag=0`，不得用清单第一档凑数
    5. 近档（非精确）时该主运行 `needVerify=true`，remark 注明「规格按 {selectedSpec} 近似」
    6. `specGuessed` 时主运行 `needVerify=true`，remark「规格按 {selectedSpec} 默认」

### `hint` 提示语（按分支原样用，可多句用空格或换行拼接）

**两边都有（有有效运价且有相似历史单，严格禁止出现“未匹配到足够相似的历史关闭单”）：**

```text
本次费用按运价中心当前有效运价生成（最新运价）。报价金额以市场运价为准。
```

**只有市场运价（有有效运价且无相似历史单）：**

```text
本次费用按运价中心当前有效运价生成（最新运价）。未匹配到足够相似的历史关闭单，故无上浮/下跌对照。
```

**只有相似历史单：**

```text
当前没有匹配的最新运价，本次费用按相似历史订单报价生成，仅供参考。建议在运价中心补充有效运价或联系管理员。
```

**两边都无 / 未调有效运价 / 调了 hits 空：**

```text
请补充运价中心的数据或联系管理员。
```

**有运价且规格为默认猜测时追加：**

```text
请提供更详细的询价信息（港口、运输方式、箱型/货量、品名等），以获得更精准的报价。
```

**指定船司/航线未命中、已按同港运价报价时追加：**

```text
未命中指定船司/航线，已按同港有效运价报价，请核对。
```

**合计涨跌与上浮/下跌提示语**（两边都有时必出，由 LLM 生成或由 `normalize` 节点兜底计算）：
本次合计与对照历史单应收合计折到同一币种对比。相对差 = (本次合计 − 历史应收合计) / 历史应收合计，百分比取绝对值四舍五入为整数。
若 LLM 未生成或生成空串，由 `normalize` 节点自动计算补齐，确保有相似历史单时必有上浮/下跌提示语与标识：

| 四舍五入后 | `alertColor` | `trendHint` |
| --- | --- | --- |
| 0% | `normal` | 当前报价与相似历史单持平。 |
| 1%–9% 且本次更高 | `normal` | 当前报价较相似历史单略有上浮，约{n}%。 |
| 1%–9% 且本次更低 | `normal` | 当前报价较相似历史单略有下跌，约{n}%。 |
| ≥10% 且本次更高 | `red` | 当前报价较相似历史单上浮约{n}%，差距较大，请确认报价明细。 |
| ≥10% 且本次更低 | `red` | 当前报价较相似历史单下跌约{n}%，差距较大，请确认报价明细。 |

`red` 只涂 `trendHint`。其余 `hint` 不涂红。只有运价、只有历史、两边都无时 `trendHint` 与 `alertColor` 都为空串。
同时，`fees[].trendText` 提供单项费用涨跌说明，`marketRates[].trend` 提供相对本次主运费单价的上涨/下跌/持平标识。

**缺项填补**（目录补了运价/历史都没有的行时追加，原型底栏）：

```text
{费用名} 在系统历史报价有缺项，已动态填补，请核对。
```

---

## 输出契约（`end.result_json`）

终点只暴露字符串 `result_json`（与抽取工作流相同：嵌套数组用 JSON 字符串，避免 Dify 数组类型丢键）。`normalize` 保证键齐全。

```json
{
  "analyzed": {
    "ioDirection": 1,
    "ioDirectionLabel": "出口",
    "logisticsType": "SEA",
    "rateType": "FCL_EXPORT",
    "rateTypeLabel": "出口整箱",
    "queryText": "出口整箱 宁波 CNNGB 洛杉矶 USLAX 定制家具 2x40HQ MSC 美西 直达 周班",
    "containerTypes": ["40HQ"],
    "selectedSpec": "40HQ",
    "quantity": 2,
    "skipRate": false,
    "carrier": "MSC",
    "routeName": "美西",
    "country": "",
    "transitType": "直达"
  },
  "steps": [
    {
      "code": "RECALL",
      "name": "检索召回",
      "progress": "done",
      "detail": "匹配运价中心有效运价 + 相似历史成交文案"
    },
    {
      "code": "RULES",
      "name": "规则引擎",
      "progress": "done",
      "detail": "按运输方式与进出口列出应报费用项，校验计费单位"
    },
    {
      "code": "LLM",
      "name": "LLM 合成",
      "progress": "done",
      "detail": "生成预填报价单草稿并注明依据"
    }
  ],
  "fees": [
    {
      "feeName": "海运费",
      "unitPrice": 2480.0,
      "quantity": 2.0,
      "currencyCode": "USD",
      "amount": 4960.0,
      "remark": "来源=运价中心 {rateId} 出口整箱 40HQ",
      "sourceType": "RATE",
      "chargeUnit": "柜",
      "requiredFlag": 1,
      "selectedFlag": 1,
      "needVerify": false,
      "trendText": "较历史下跌 100USD（约 4%）"
    }
  ],
  "totalAmount": 6040.0,
  "totalCurrency": "USD",
  "hint": "目的港 THC、DO 费在系统历史报价有缺项，已动态填补，请核对。",
  "trendHint": "当前报价较相似历史单上浮约20%，差距较大，请确认报价明细。",
  "alertColor": "red",
  "marketRates": [
    {
      "priceText": "$2,480/40HQ",
      "rateDate": "2024-07-01",
      "trend": "持平",
      "unitPrice": 2480.0,
      "containerType": "40HQ",
      "carrier": "",
      "rateId": ""
    }
  ],
  "similarQuotes": [
    {
      "quoteNo": "SO20241218001",
      "dealDate": "2024-12-18",
      "inquiryStatusLabel": "已成交",
      "summary": "同航线 CNNGB-USLAX 2x40HQ 海运费 USD 2580/柜"
    }
  ],
  "competitorHint": null
}
```

缺省：`fees`/`marketRates`/`similarQuotes` 为 `[]`；`hint`、`trendHint`、`alertColor` 为 `""`；`totalAmount` 为 `0`；`totalCurrency` 为 `"USD"`；`competitorHint` 为 `null`；`analyzed` 数字/布尔用 `0`/`false`，字符串 `""`，数组 `[]`。`steps` 三步恒在，HTTP 失败仍 `progress=done`（空召回），仅 LLM 结构化失败时 `LLM.progress=failed` 且 `fees=[]`。`alertColor` 只允许 `red`、`normal`、空串。

### 侧边映射

**`marketRates[]`** ← 运价 `hits[]`（默认 1 条；侧边仍整条返回）：

| 出参 | 来源 |
| --- | --- |
| `unitPrice` | 选档后的 `specPrices[].amount`；无同族可对则 `0`，不得用清单第一档 |
| `containerType` | `analyzed.selectedSpec` |
| `priceText` | `$` + 千分位单价 + `/` + 箱型或单位 |
| `rateDate` | `effectiveDate` 或 `updateTime` 日期 |
| `trend` | **市场运价涨跌**：相对本次采用主运费单价：高→`上涨`，低→`下跌`，否则 `持平`；无法比则 `""`。不是费用行涨跌对照 |
| `rateId` | `bizId` |
| `carrier` | `carrier` |

**`similarQuotes[]`** ← 订单 `hits[]`（全部返回）：

| 出参 | 来源 |
| --- | --- |
| `quoteNo` | `bizNo`（订单号；原型 QUO- 仅示意） |
| `dealDate` | `updateTime` 日期，否则 `etd` |
| `inquiryStatusLabel` | 固定展示「已成交」（关闭单） |
| `summary` | `{originPortCode}-{destPortCode} {cargoSpec或箱型} {第一条应收费用名} {amount}{currency}` |

禁止把 `orderNo` 写入 `fees[].remark`。

### `fees[]` 与原型表

`fees[]` 数组每个对象必须严格包含以下键名（`synthesize` prompt 必须显式声明，`normalize` 做多别名兼容与 remark 兜底）：
- `feeName`: 费用中文全称（如「海运基本运费」、「燃油附加费」、「目的港操作费」、「报关代理费」等；禁止用 `name`/`fee_name` 导致下游读取为空；`normalize` 兼容 `name`/`fee_name`/`chargeName`/`itemName`，空时从 `remark` 中正则兜底提取）。
- `chargeUnit`: 计费单位（如「箱」、「票」、「CBM」、「KG」；禁止直接透传输入单据的 `unit` 导致字段落空；`normalize` 兼容 `unit`/`charge_unit`/`billingUnit`，空时从 `remark` 的 `/单位` 中正则兜底提取）。
- `unitPrice`: 单价数值。
- `quantity`: 数量数值。
- `amount`: 金额数值（`unitPrice * quantity` 四舍五入保留 2 位）。
- `currencyCode`: 币种代码（如 `USD`、`CNY`）。
- `sourceType`: 来源类型（`RATE` / `HISTORY` / `DIFY`）。
- `remark`: 费用来源说明。
- `requiredFlag`: 是否必选（`1` 或 `0`）。
- `selectedFlag`: 是否勾选（`1` 或 `0`）。
- `needVerify`: 是否需复核（`true` 或 `false`，对齐原型高亮行：`needVerify=true` 时前端可黄底高亮，如提单费「参考价格，请核实」或规格近档；询价页若不识该键可忽略）。
- `trendText`: 给行备注区的涨跌短句；无对照可为 `""`。

---

## 图计划

| 节点 ID | `data.type` | 输入 | 输出 |
| --- | --- | --- | --- |
| `start` | `start` | 上表 start 变量（含 `supplement`） | 同名 |
| `infer_route` | `parameter-extractor` | 拼接后的询价基础字段 | `io_direction` number、`rate_type` string、`container_type` string、`quantity` number、`skip_rate` boolean + `__is_success` |
| `need_supp` | `if-else` | `supplement` 去空白非空 | 非空 → `parse_supplement`；空 → `empty_supp` |
| `parse_supplement` | `parameter-extractor` | `supplement` | `carrier`、`route_name`、`route_code`、`country`、`transit_type`、`origin_terminal`、`dest_terminal`、`schedule_note`、`spec_hint` + `__is_success` |
| `empty_supp` | `code` | 无 | 同上各键空串 |
| `assemble` | `code` | start + infer + 补充解析 | `io_direction`、`logistics_type`、`rate_type`、`biz_type`、`query_text`、`container_types_json`、`quantity`、`skip_rate`、`info_insufficient`、`rate_body`、`order_body`、`charge_body`、`analyzed_json` |
| `need_rate` | `if-else` | `assemble.skip_rate` | case `false` 去搜运价；否则 `empty_rates` |
| `search_rates` | `http-request` | `rate_body` | `body` / `status_code` |
| `empty_rates` | `code` | 无 | `body` = `{"data":{"hits":[]}}` |
| `search_orders` | `http-request` | `order_body` | `body` / `status_code` |
| `list_charges` | `http-request` | `charge_body` | `body` / `status_code` |
| `fetch_fx` | `http-request` GET 公开 USD | 无 Body | `body` |
| `fx_fallback` | `http-request` GET 备源 | 仅主汇率失败 | `body` |
| `pack_context` | `code` | 三检索 body + fx + assemble | `context_json`（截断保护）、`fx_json`、`recall_ok` |
| `synthesize` | `llm` | `context_json` + 算费规则 | `text` |
| `normalize` | `code` | LLM text + pack + assemble.analyzed | `result_json` |
| `end` | `end` | `result_json` | API 键 `result_json` |

**if-else `need_rate`：** `assemble.skip_rate = 0`（已选出主表）走 `search_rates`；无主表 `sourceHandle: false` → `empty_rates`。两路都进 `pack_context`。

**`info_insufficient`：** 现表示 `specGuessed`（默认柜型/CBM）。无主表 skip 时 hint 走补运价中心句，不走「信息不足」。

**边（逻辑）：**

- `start` → `infer_route` → `assemble`
- `start` → `need_supp` → `parse_supplement` / `empty_supp` → `assemble`（两路输出同名变量；需要则 `variable-aggregator`）
- `assemble` → `need_rate` → `search_rates` / `empty_rates` → `pack_context`
- `assemble` → `search_orders` → `pack_context`
- `assemble` → `list_charges` → `pack_context`
- `assemble` → `fetch_fx` →（失败）`fx_fallback` → `pack_context`；成功也进 `pack_context`
- `pack_context` → `synthesize` → `normalize` → `end`

并行扇出合法；`assemble` 等 infer + 补充解析；`pack_context` 等齐四路。HTTP 节点打开 retry；失败路径接到输出空 body 的 code，避免整图失败。

**`infer_route`：** 模型 `qwen3.7-flash-2026-07-15`，`reasoning_mode: prompt`，`temperature: 0.1`，关 thinking。输入含基础字段与补充信息。只抽进出口、运价类型、规格。未提供柜型或读不出时规格填空字符串，禁止默认猜 40HQ（40HQ 仅在 assemble 中用于运价选档提示，不污染相似历史单）；失败时 assemble 用港码规则、默认出口。不解析船司航线。无主表才 skip。

**`parse_supplement`：** 同上抽取配置。只抽补充信息表内字段。禁止把「尽量快」写成直达，禁止把品名写成船司。

**`assemble`：** 港码规则覆盖进出口，推不出默认出口。运输方式归一。海运无整箱/拼箱默认 FCL 表（仅运价选档使用 `40HQ`/`quantity=1` 并标 `specGuessed`；若用户未传规格，订单检索 Body 不传 `containerType`）。无主表才 `skip_rate`。按模板拼检索句与三个 JSON Body。

**`pack_context`：** 解析 R 包 `data.hits` / `data.items`；去掉进价类键（若误出则丢）；把 analyzed（含抽出键与 preferred spec）、运价 `hits[0]`（含完整 `specPrices`/`extras`）、订单 hits（每条 `fees[]` 全留）、费用项 `items[]` 全部、汇率表压成给 LLM 的 JSON。订单 hits 超长可截至 8 条；**禁止截**每单 `fees[]` 与费用项 `items[]`。

**`synthesize`：** 模型 `qwen3.7-plus`。`context.enabled: false`。只输出一个 JSON 对象（不要 Markdown 围栏）。系统提示 = 算费规则 + 规格价选档 + 输出键表 + 2 个短例（有运价精确档 / 仅历史）。强调：只用 `hits[0]`；从完整 `specPrices` 选最相似一档；按 `feeKindLabel` 分行。user = `{{#pack_context.context_json#}}`。

**`normalize`：** 剥 ````json`；缺键补缺省；`competitorHint=None`；`steps` 强制三步；`amount=unitPrice*quantity`（四舍五入 2 位）；`needVerify` 非 bool 则 false；`alertColor` 非 `red`/`normal` 则 `""`；**核心纠偏与兜底：当有相似历史单时，强制剔除或纠正“未匹配到足够相似的历史关闭单，故无上浮/下跌对照”，替换为两边都有的标准 hint；当两边都有且 `trendHint` 为空时，代码自动根据本次合计与历史应收合计计算相对差百分比并填补 `trendHint`、`alertColor`、`marketRates[].trend`**；去掉旧句「与相似历史案例差价较大，请复核后再对外报价。」；无双边对照、LLM 失败时清空 `trendHint` 与 `alertColor`；LLM 失败或非对象 → 空费用 + 对应 hint + `LLM.progress=failed`。

---

## 原型覆盖

| 原型块 | 本应用 |
| --- | --- |
| 顶栏询价号/客户/航线/货/服务 | 入参回显由询价页自己绑详情；JSON 不强制重复，`analyzed` 可供调试 |
| 补充更详细信息 | `start.supplement` → `parse_supplement`；空则跳过 LLM |
| 生成报价推荐 | 工作流一次运行 |
| 01 检索召回 | `search_rates` + `search_orders` → `steps[0]` + 侧边 |
| 02 规则引擎 | `list_charges` → `steps[1]`（目录，不是 billing_rule） |
| 03 LLM 合成 | `synthesize` → `steps[2]` + `fees` |
| 预填报价草稿表 | `fees[]` |
| 合计 | `totalAmount` + `totalCurrency` |
| 黄底须核对行 | `needVerify=true` |
| 缺项 hint | `hint` |
| 底栏合计涨跌（红/温和） | `trendHint` + `alertColor`（`red` 只涂这一句） |
| 右边市场运价 + 涨跌 | `marketRates[]` |
| 相似历史单 + 已成交 | `similarQuotes[]` |
| 竞品价参考 | 不做，`competitorHint=null` |
| 采用并进入报价流程 | 询价前端已有，本应用不落库 |

---

## Tasks

### Task 0: 核对节点 schema

**Files:** 只读 `dify-docs` MCP、`$dify-workflow-dsl` 示例、`references/node-schemas.md`

- [ ] **Step 1:** 核对 `http-request`：POST JSON、Bearer、自定义头、`body` 输出名、retry、失败分支。
- [ ] **Step 2:** 核对 `if-else` 的 `sourceHandle`（case id vs `false`）与并行汇合；需要则抄 `variable-aggregator`。
- [ ] **Step 3:** 核对 `end` 输出 string；环境变量 secret 在 HTTP 中的引用写法。
- [ ] **Step 4:** 记录 tongyi identity（从 `inquiry_quote_extract.yml` 原样抄）。
- [ ] **Step 5:** 核对 `parameter-extractor`：Flash 节点 `reasoning_mode: prompt`、失败字段 `__is_success` / `__reason`；本图有 `infer_route` 与 `parse_supplement` 两处。

### Task 1: 领域文档

**Files:**

- `docs/quote-recommend/CONTEXT.md`（grilling 已建，薄指针）
- `CONTEXT-MAP.md`（grilling 已改）

- [x] **Step 1:** 用语写入询价 / AI 数据 glossary；本仓不另造同义词。
- [x] **Step 2:** CONTEXT-MAP 已有「报价推荐」。

### Task 2: 写 Workflow DSL

**Files:**

- Create: `dsl/workflows/inquiry_quote_recommend.yml`

- [ ] **Step 1:** 按图计划写节点与边；`environment_variables` 三个本地测试值写入 `value`。
- [ ] **Step 2:** `infer_route` 判定进出口 / 运价类型 / 规格；`parse_supplement` 抽补充信息；空补充走 `empty_supp`；`assemble` 按接口逻辑填三份 Body（运价有则精确、订单检索句、费用项不收这些键）。
- [ ] **Step 3:** `pack_context` / `normalize` 实现失败可运行。
- [ ] **Step 4:** HTTP path 只用 `{{#env.AIDATA_BASE_URL#}}/agent/...`（以 Task 0 实际 env 语法为准）。
- [ ] **Step 5:** `synthesize` 写入算费规则、规格价选档与 JSON 键；禁止密钥进 prompt。
- [ ] **Step 6:** 自检：`version: "0.7.0"` 有引号；节点 ID 无连字符；`end` 仅 `result_json`；无竞品字段实值。`AIDATA_*` 为本地测试实值。

### Task 3: 严格校验

- [ ] **Step 1:** `python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_recommend.yml`
- [ ] **Step 2:** 失败则修 YAML 至 exit 0。
- [ ] **Step 3:** 交付说明：导入后重连模型、核对 `AIDATA_*` 环境变量、授权 HTTP。本 YAML 不接询价服务。

**试跑样例 A（海运出口整箱，应对齐原型结构）：**

```text
logistics_type=SEA
origin_port_code=CNNGB dest_port_code=USLAX
origin_port_name=宁波 dest_port_name=洛杉矶
cargo_name=定制家具 cargo_spec=2x40HQ
service_scope=到港 All-in
customer_name=宁波索菲亚家居
supplement=
```

期望：`analyzed.ioDirection=1`，`rateType=FCL_EXPORT`，`quantity=2`，`selectedSpec=40HQ`；`steps` 三项；有运价则主运费来自 `hits[0].specPrices` 中 `40HQ`（完整清单里选，不是接口截档），`quantity=2` 且 `sourceType=RATE`；关联费用按 `feeKindLabel` 分行；`marketRates` 至多对应该一条；`competitorHint` JSON null。

**试跑样例 E（补充信息精确键）：**

```text
同 A，且 supplement=尽量MSC直达 美西航线 周班
```

期望：运价 Body 含 `carrier=MSC`、`transitType=直达`、`routeName=美西`；`queryText` 同时含 MSC、美西、直达、周班（第二轮丢掉结构化键后仍靠这些词向量排序）；费用项 Body **没有**这些键；`analyzed.carrier=MSC`。

**试跑样例 F（规格近档）：** 运价命中 `specPrices` 仅有 `40GP`、无 `40HQ`，询价 `2x40HQ`。期望：主运费用 `40GP`，`selectedSpec=40GP`，`needVerify=true`，remark 含近似；不得改用 `20GP` 或清单里无关的 OT。

**试跑样例 B（规格不足）：**

```text
customer_name=宁波索菲亚家居
logistics_type=SEA
origin_port_code=CNNGB dest_port_code=USLAX
origin_port_name=宁波 dest_port_name=洛杉矶
cargo_spec=
```

期望：`skipRate=false`，`rateType=FCL_EXPORT`，`selectedSpec=40HQ`，`quantity=1`，`specGuessed=true`，走运价节点；hint 含「请提供更详细的询价信息」；可仍打订单/费用项。

**试跑样例 C（空运进口，无运价表）：**

```text
customer_name=宁波索菲亚家居
logistics_type=AIR
origin_port_code=USLAX dest_port_code=CNNGB
origin_port_name=洛杉矶 dest_port_name=宁波
cargo_spec=200KG
```

期望：`ioDirection=2`，`skipRate=true`，不打 `AIR_EXPORT`，不调有效运价接口；hint 含「请补充运价中心的数据或联系管理员。」（有历史则用仅供参考整句）；不把出口空运卖价当进口报价。

**试跑样例 D（仅历史）：** 人工在试跑中把运价源关掉或用不存在港码。期望：hint 含「仅供参考」；`sourceType=HISTORY`；remark 无订单号。

---

## 明确不做（YAGNI）

- 不做 Chatflow / Agent v2 / 独立 Agent App / 知识库
- 召回前 LLM 不重写运输方式、不手写货运类型码、不推翻港码已定进出口；无柜型时海运/铁运默认 `40HQ`
- 补充信息没写明则不编造码头 / 船司 / 航线 / 航线代码 / 直达中转；不把船期写成 `validOn` 或 `transitType`
- 不把补充信息抽出的键写入费用项 Body
- 不做竞品价；不做询价落库；不做前端「采用并进入报价流程」
- 不调 `billing_rule`、不调运价中心非 Agent 接口、不调 inquiry HTTP
- 不实现 `get_*_record` / `list_rate_types` / `list_data_sources`
- 不从多条运价 hits 拼报价；不因箱型入参截 `specPrices`；不拿清单第一档冒充选档
- 运价空结果不二次调用、不放开港口向量；丢掉有则精确结构化键时禁止从 `queryText` 删船司/航线/国家/中转
- 不把【匹配到的市场运价】【相似历史单】【费用明细】整段散文当 API 主输出（结构化进数组；【报价说明】进 `hint`）
- 不在未要求时提交 git commit
- 不改 `digital-logistics` 询价 Java / AI 数据 Java

---

## Spec 覆盖自检

| 需求 | 对应 |
| --- | --- |
| 用询价基础字段 | `start` 变量 |
| 补充信息 | `supplement` + `parse_supplement`；按接口逻辑填精确键或检索句 |
| 运输/进出口/规格/航线 | 港码规则 + `infer_route` + 补充解析 + `assemble` 转换 |
| 运价中心接口 | `POST /agent/rate/search`（有则精确填抽出键；报价从完整 `specPrices` 选最相似档） |
| 相似历史订单接口 | `POST /agent/order/search`（补充信息进检索句；`fees[]` 全出） |
| 计费项接口 | `POST /agent/settlement/charge-items`（仍只 logistics+进出口） |
| LLM 推荐报价单 | `synthesize` 选档 + `normalize` → `fees` |
| 原型三步 + 草案表 + 侧边 | `steps` / `fees` / `marketRates` / `similarQuotes` / `hint` |
| 不管竞品 | `competitorHint: null` |
| 算费与提示语 | 本文件算费规则 + `hint` 原文 |
| 不是智能体 | Architecture |
| 不指向后端 Spec | 实施权威仅本文件 + 原型 + CONTEXT |
