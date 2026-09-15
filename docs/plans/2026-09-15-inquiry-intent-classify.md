# 询价意图识别工作流 Implementation Plan

> **For agentic workers:** 按 Task 顺序逐步实施；实施时显式使用 `$dify-workflow-dsl` skill，并先查 `dify-docs` MCP。

**Goal:** 生成可导入 Dify 1.16 的 Workflow DSL：输入一段文字（通常是电子邮件全文），由大模型判断是否为**询价需求**；终点只返回布尔值 `true` / `false`。

**Architecture:** 单次运行的 `workflow`（非 Chatflow、非独立 Agent App、不用 Agent v2 节点）。图结构：`start → parameter-extractor → code → end`。参数提取器做二分类；`code` 把提取失败与非布尔值一律收成 `false`（失败即否）。不接知识库、工具、HTTP。

**为何不是智能体：** 无动态选工具、无多步任务。仓库约定「工具选择动态时才用 Agent」。本需求是固定二分类，用参数提取器即可。对外仍可称「询价意图识别」应用。

**Tech Stack:** Dify App DSL `"0.7.0"`、`$dify-workflow-dsl`、`dify-docs` MCP、`scripts/validate_dsl.py`。

**Domain docs:** 同一 context「询价字段抽取」（`CONTEXT.md`）。本应用是抽取工作流的**前置闸门**，不调用、不修改 `inquiry_quote_extract.yml`。

---

## Global Constraints

- 目标：Dify 1.16.x / DSL `version: "0.7.0"`（必须加引号）
- 模式：`app.mode: workflow`
- 落盘：`dsl/workflows/inquiry_intent_classify.yml`
- 节点 ID：仅字母、数字、下划线，长度 1–50
- 禁止写入 API Key、credential ID、MCP URL、私有 dataset ID
- 交付前必须：`python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_intent_classify.yml`
- 导入后须在目标工作区重连模型凭据后再试跑；禁止声称「导入即可运行」
- 模型占位与抽取工作流对齐：`langgenius/tongyi/tongyi` + `qwen3.7-plus`（导入后重连）
- `parameter-extractor`：`reasoning_mode` 优先 `function_call`；下游不得假定提取必成功

---

## 领域用语（实施时写入 `CONTEXT.md`）

**待判文本**：
本应用唯一输入。一段非结构化文字，通常是电子邮件（含主题行、正文、签名、免责声明、历史转发均可原样粘贴）。
_Avoid_: 询价文本（那是抽取工作流的输入，已假定为询价）

**询价需求**：
待判文本的核心意图是向本方（物流/货代）索取运价、费用或报价（询盘/询价/请报价/请给 rate 等）。即使起运地、货量不全，只要在要价，即为询价需求。
_Avoid_: 把订舱指令、轨迹查询、对账、已方发出的报价单正文当成询价需求

**判定结果**：
工作流对外唯一验收对象。API 键 `is_inquiry`，类型布尔：`true` 有询价需求，`false` 没有。提取失败、空输入、无法判断均为 `false`。
_Avoid_: 字符串 `"true"`/`"false"`、置信度、理由字段（本版不做）

---

## 判定规则（写入 `classify_intent.instruction`）

判定对象是**整段待判文本的商业意图**，不是「是否像一封邮件」。签名、免责声明、广告页脚单独出现不算询价。

### 判 `true`（须有索价意图）

- 明确询盘/询价/请报价/请报运价/请给 rate / quotation / RFQ / 帮忙看看价格
- 给出货盘并问费用（即使只有部分要素：港口、品名、重量、柜型、条款等）
- 追问「上次询的那票什么时候能出价格」、催报价
- 对尚未成交的运价继续议价（还价、再优惠、再报一版）——仍属询价需求

### 判 `false`

- 空、纯签名、乱码、与物流报价无关的闲聊
- 营销邮件、会议邀请、系统通知
- 纯操作：订舱确认、补料、报关资料、改单、放货，且未再要价
- 轨迹/POD/到货查询
- 对账、发票、付款、催款
- 投诉、索赔、无报价诉求的售后
- 本方已发出的报价单/运价表作为正文、收件方只致谢或「收到」，没有新的要价
- 仅问「你们做不做某条航线/某产品」而不要价格

### 冲突与长邮件

- 正文既有询价又有订舱/对账：只要存在未完成的索价，判 `true`
- 转发链/回复链：整段一起看；任一清晰索价则 `true`
- 无法判断 → `false`（偏严，避免把非询价送进抽取）

与 ADR-0001 无冲突：本应用输出单布尔，不取「先出现字段」。

---

## 输出契约

| API 键 | 类型 | 取值 | 缺省 |
| --- | --- | --- | --- |
| `is_inquiry` | boolean | `true` / `false` | `false` |

`end` 节点只暴露这一键。不要输出 `reason`、`confidence`、原文回显。

---

## 图计划

| 节点 ID | `data.type` | 输入 | 输出 |
| --- | --- | --- | --- |
| `start` | `start` | 用户：`source_text`（paragraph，必填，max 10000） | `source_text` |
| `classify_intent` | `parameter-extractor` | `query: [start, source_text]` | `is_inquiry`（boolean）+ `__is_success` / `__reason` |
| `normalize_result` | `code` | `raw_flag` ← `classify_intent.is_inquiry`；`ok` ← `classify_intent.__is_success` | `is_inquiry`（boolean） |
| `end` | `end` | `is_inquiry` ← `normalize_result.is_inquiry` | API：`is_inquiry` |

**边：**

- `start` → `classify_intent`（sourceHandle 默认）
- `classify_intent` → `normalize_result`
- `normalize_result` → `end`

**`classify_intent`：**

- `parameters`: 仅一项 `is_inquiry`，`type: boolean`，`required: true`
- `instruction`: 上文判定规则的压缩版 + 2～3 条正负例子
- `reasoning_mode: function_call`
- LLM `context.enabled: false`（若该节点 schema 要求 context 字段则按 skill 示例抄）
- `temperature: 0.1`，关闭 thinking（与抽取工作流一致）

**`normalize_result`（失败即否）：**

- `__is_success` 非真 → `false`
- `raw_flag` 为 Python `True` / `"true"` / `"True"` / `1` → `true`
- 其余 → `false`

---

## 与现有应用关系

| | 询价意图识别（本计划） | 询价字段抽取 |
| --- | --- | --- |
| DSL | `dsl/workflows/inquiry_intent_classify.yml` | `dsl/workflows/inquiry_quote_extract.yml` |
| 输入 | `source_text`（待判文本） | `inquiry_text`（已假定为询价） |
| 输出 | `is_inquiry` boolean | `result_json` |
| 编排 | 独立 App；本仓库不把两者用边连起来 | 不变 |

调用方若要串：先跑本应用，仅 `true` 再调抽取。本计划不实现编排。

**CONTEXT-MAP：** 不新增第四个 context。在「询价字段抽取」条下注明该 context 现有两份 DSL（识别 + 抽取）。

---

## Tasks

### Task 0: 核对节点 schema 与 boolean 终点

**Files:**

- 只读：`dify-docs` MCP、`$dify-workflow-dsl` 示例、`references/node-schemas.md`

- [ ] **Step 1:** 核对 `parameter-extractor` 的 `boolean` 参数、`reasoning_mode`、query 写法。
- [ ] **Step 2:** 核对 `end` 输出变量类型是否支持 boolean；若导入侧只认 string，则 `end` 仍用 boolean 并在交付说明写明，**不要**改成 `"true"` 字符串除非 schema 禁止 boolean。
- [ ] **Step 3:** 记录模型占位（与 `inquiry_quote_extract.yml` 同一 provider/name）。

### Task 1: 更新领域文档

**Files:**

- Modify: `CONTEXT.md`
- Modify: `CONTEXT-MAP.md`

- [ ] **Step 1:** 在 `CONTEXT.md` 增加「待判文本」「询价需求」「判定结果」；明确与「询价文本」的边界。
- [ ] **Step 2:** `CONTEXT-MAP` 询价条注明两份 DSL 文件名。

### Task 2: 写 Workflow DSL

**Files:**

- Create: `dsl/workflows/inquiry_intent_classify.yml`

- [ ] **Step 1:** 按图计划写 4 节点 3 边；`app.name` = `询价意图识别`。
- [ ] **Step 2:** `classify_intent.instruction` 写入判定规则与正负例。
- [ ] **Step 3:** `normalize_result` 实现失败即否。
- [ ] **Step 4:** `dependencies` 原样抄抽取工作流的 tongyi marketplace identity，禁止编造。
- [ ] **Step 5:** 自检：无密钥；`version: "0.7.0"` 有引号；节点 ID 无连字符；`end` 仅 `is_inquiry`。

### Task 3: 严格校验

- [ ] **Step 1:** `python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_intent_classify.yml`
- [ ] **Step 2:** 失败则修 YAML 至 exit 0。
- [ ] **Step 3:** 交付说明：导入后重连模型凭据；本应用不抽取字段。

**试跑样例 A（true，标准询盘邮件）：**

```text
Subject: 询价 — 宁波到洛杉矶 1x40HQ
您好，请报价：
起运宁波，目的洛杉矶，FCL 40HQ，货塑料配件约 18 吨，CIF。
麻烦尽快给海运费和附加费。谢谢。
```

期望：`is_inquiry` = `true`

**试跑样例 B（true，要素不全仍要价）：**

```text
有一批货要走美国，大概 200kg，空运能帮忙看看价格吗？
```

期望：`true`

**试跑样例 C（false，订舱不询价）：**

```text
请按上周确认的运价帮我订舱，SO 附件已发，谢谢。
```

期望：`false`

**试跑样例 D（false，轨迹）：**

```text
这票货到哪了？提单号 EGLV123，请发一下最新动态。
```

期望：`false`

**试跑样例 E（true，长邮件里夹询价）：**

```text
对账那票我们下周处理。另外再询一票：上海到汉堡，LCL 3CBM，请报价。
```

期望：`true`

**试跑样例 F（false，空/无关）：**

```text
Best regards,
Tom
```

期望：`false`

---

## 明确不做（YAGNI）

- 不做 Chatflow / 多轮澄清 / Agent v2 / 独立 Agent App
- 不做知识库、MCP 工具、HTTP 回写
- 不输出理由、置信度、分类标签（询价/订舱/对账等多类）
- 不在本 DSL 内调用或包含字段抽取
- 不解析附件、不要求单独的邮件主题字段（主题若在正文里则整段喂入）
- 不在未要求时提交 git commit

---

## Spec 覆盖自检

| 需求 | 对应 |
| --- | --- |
| 输入一段文字/邮件 | `start.source_text` |
| 大模型判断是否询价 | `classify_intent` parameter-extractor |
| 只返回 true/false | `end.is_inquiry` boolean + code 归一 |
| 提取失败不误报 | code 失败即否 |
| 不用智能体 | Architecture 说明 |
| 与抽取解耦 | 独立 YAML，不改抽取图 |
