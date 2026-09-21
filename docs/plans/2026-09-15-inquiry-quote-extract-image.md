# 询价图片字段抽取工作流 Implementation Plan

> **For agentic workers:** 按 Task 顺序逐步实施；实施时显式使用 `$dify-workflow-dsl` skill，并先查 `dify-docs` MCP。字段规则以 `dsl/workflows/inquiry_quote_extract.yml` 与 `docs/plans/2026-08-25-inquiry-quote-extract.md` 为准，本计划只补「图 → 文」差异，禁止另写一套枚举。

**Goal:** 生成可导入 Dify 1.16 的 Workflow DSL：输入**一张询价图片**（及可选客户名回退开关），结构化抽出与「询价字段抽取」**完全相同**的 `result_json`（11 键 `{ value, confidence }` + `supplement` 字符串）。

**Architecture:** 单次运行的 `workflow`（非 Chatflow、非独立 Agent App、不用 Agent v2 节点）。图结构：

`start → read_image（llm + vision）→ extract_fields（parameter-extractor）→ build_json（code）→ end`

用户输入节点只收集文件，不解析内容。官方接法：图片交给带视觉能力的 LLM；参数提取器的输入是**文本**。因此先视觉转写可见文字，再复用文本抽取的提取器 + 装配逻辑。

**为何不是智能体：** 无动态选工具、无多步任务。仓库约定「工具选择动态时才用 Agent」。本需求是固定字段抽取，只是入口从段落换成单张图片。

**Tech Stack:** Dify App DSL `"0.7.0"`、`$dify-workflow-dsl`、`dify-docs` MCP、`scripts/validate_dsl.py`。

**Domain docs:** 同一 context「询价字段抽取」（`CONTEXT.md`）。本应用是抽取工作流的**图片入口孪生**，不调用、不修改 `inquiry_quote_extract.yml`。

**依据（dify-docs）：**

- 用户输入：自定义单文件字段；图片须由后续视觉 LLM 处理（[用户输入 / 文件输入](https://docs.dify.ai/zh/cloud/use-dify/nodes/user-input#文件输入)）。
- LLM：启用 Vision，`detail` 高/低；选择器指向文件变量（[LLM / 视觉能力配置](https://docs.dify.ai/zh/cloud/use-dify/nodes/llm#视觉能力配置)）。
- 参数提取器：输入变量是**待抽取的文本**（[参数提取器](https://docs.dify.ai/zh/cloud/use-dify/nodes/parameter-extractor)）。不要把图片 selector 当作 `query`。
- 文档提取器：面向 PDF/Office 等文档，**不**作为本版图片 OCR。

---

## Global Constraints

- 目标：Dify 1.16.x / DSL `version: "0.7.0"`（必须加引号）
- 模式：`app.mode: workflow`
- 落盘：`dsl/workflows/inquiry_quote_extract_image.yml`
- 节点 ID：仅字母、数字、下划线，长度 1–50
- 禁止写入 API Key、credential ID、MCP URL、私有 dataset ID
- `end` 只暴露 `result_json`（string），键集合与文本抽取完全一致（11 业务键 + `supplement`）
- 单值冲突：转写文本中**先出现**（阅读顺序：上→下、左→右）即先出现；延续 ADR-0001
- 交付前必须：`python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_extract_image.yml`
- 导入后须在目标工作区重连模型凭据后再试跑；禁止声称「导入即可运行」
- `dependencies` 原样抄 `inquiry_quote_extract.yml` 的 tongyi marketplace identity，禁止编造
- LLM 节点必须带 `context.enabled: false` 与 `variable_selector: []`
- 视觉模型：`read_image` 用 tongyi 已列视觉模型 `qwen3-vl-flash`（`provider: langgenius/tongyi/tongyi`），带 Vision；只换 `model.name`，不编造 `provider_id`。`extract_fields` 继续用 `qwen3.7-plus`（只吃转写文本）
- `read_image` 参数按插件 `qwen3-vl-flash.yaml` 适配（非 plus）：`temperature: 0.1`（范围 0–1.99）、`top_p: 0.8`（上限 0.99）、`max_tokens: 8192`（上限 32768）、`enable_thinking: false`（该系列默认关思考，OCR 不需要）、`repetition_penalty: 1.0`（转写不惩罚重复数字/代码）。不传 `thinking_budget`（仅思考开启时生效）。上下文窗口 131072，小于 plus 的 262144，单图转写足够

---

## 领域用语（实施时写入 `CONTEXT.md`）

**询价图片**：
本应用主输入。客户侧发来的询盘截图、扫描件或拍照（邮件正文截图、询价表、微信/聊天截图等）。单文件、仅图片类型。
_Avoid_: 询价文本（那是文本抽取工作流的输入）；PDF/多图本版不做

**转写文本**：
`read_image` 从询价图片得到的可见文字，作为下游抽取的「原文」。只转写、不翻译、不补全。看不清则留空，禁止臆造。
_Avoid_: 把模型对图片的摘要、推测航线、翻译英文当成转写文本

其余术语（客户名称含 `fuzzy_match_customer`、运输方式、紧急程度、起运/目的地、货品、条款、服务范围、抽取结果 JSON）与文本抽取同一 glossary，不另造同义词。

---

## 输入契约

| 变量 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `inquiry_image` | `file`（仅 image） | 是 | — | 一张图片；允许本地上传与 URL（实施时按 skill 示例抄 `allowed_file_*`） |
| `fuzzy_match_customer` | number | 否 | `0` | 与文本抽取相同：`0` 仅公司名；`1` 无公司名→人名→邮箱 `@` 前用户名。有公司名一律优先公司名 |

不接收 `inquiry_text`。不接收多文件列表。

---

## 输出契约

与 `inquiry_quote_extract.yml` **逐键相同**：

- API 键：`result_json`（JSON 字符串）
- 11 业务键：`customer_name`、`transport_mode`、`urgency_level`、`origin_port_en`、`origin_port_zh`、`dest_port_en`、`dest_port_zh`、`cargo_name`、`cargo_spec`、`trade_terms`、`service_scope`
- 每键 `{ "value": string, "confidence": "置信高"|"置信中"|"置信低" }`
- `supplement`：字符串。与文本抽取相同：原 `extract_fields` 抽出九线索后由 `build_json` 拼成一段文字（不是对象），缺省 `""`
- 缺省：业务键 `value=""` 且 `confidence="置信低"`；`supplement=""`
- 封闭枚举、地点 en/zh、模糊客户名回退、`supplement` 拼装：全部照抄文本抽取的 `build_json`，不要分叉

视觉转写失败或图中无字：仍输出完整 11 键空值 JSON + `supplement=""`，工作流本身成功结束。

---

## 图计划

| 节点 ID | `data.type` | 输入 | 输出 |
| --- | --- | --- | --- |
| `start` | `start` | `inquiry_image`（file/image，必填）；`fuzzy_match_customer`（number，默认 0） | 同左 |
| `read_image` | `llm` | vision：`[start, inquiry_image]`，`detail: high`；prompt 只要求转写 | `text`（转写文本） |
| `extract_fields` | `parameter-extractor` | `query: [read_image, text]`；instruction 引用 `{{#start.fuzzy_match_customer#}}` | 与文本抽取相同的业务字段 + `{field}_confidence` + `customer_person_name` / `customer_email` + 9 个 supplement 键 + `__is_success` |
| `build_json` | `code` | 转写文本 + 开关 + 提取器各字段（与文本抽取 `build_json` 同逻辑） | `result_json` |
| `end` | `end` | `[build_json, result_json]` | `result_json` |

**边：**

- `start` → `read_image`
- `read_image` → `extract_fields`
- `extract_fields` → `build_json`
- `build_json` → `end`

禁止环。每个节点从 `start` 可达。

### `read_image`（只转写）

- `prompt_template`：system 规定「OCR/转写员」；user 只给转写指令，**不要**在这一步抽字段。
- 要求：按阅读顺序输出可见中英文、数字、代码、邮箱；手写同样转写；模糊处不要猜；禁止翻译、禁止补港口码、禁止写解释或 Markdown 标题。
- `vision.enabled: true`，`configs.detail: high`（截图/表格偏复杂），`variable_selector: [start, inquiry_image]`。
- `model.name: qwen3-vl-flash`；`completion_params`：`temperature: 0.1`、`top_p: 0.8`、`max_tokens: 8192`、`enable_thinking: false`、`repetition_penalty: 1.0`。
- 不接知识库。`memory.window.enabled: false`。

### `extract_fields` / `build_json`

从 `inquiry_quote_extract.yml` **复制** instruction、parameters、`reasoning_mode`、`build_json` 代码与变量装配。仅改：

- `query`：`[read_image, text]` 而非 `[start, inquiry_text]`
- `build_json` 的 `inquiry_text` selector：`[read_image, text]`
- instruction 首句改为「输入是询价图片的转写文本」

`vision.enabled: false`（提取器不看图）。

---

## 与现有应用关系

| | 询价字段抽取 | 询价图片字段抽取（本计划） |
| --- | --- | --- |
| DSL | `dsl/workflows/inquiry_quote_extract.yml` | `dsl/workflows/inquiry_quote_extract_image.yml` |
| 输入 | `inquiry_text` + `fuzzy_match_customer` | `inquiry_image` + `fuzzy_match_customer` |
| 输出 | `result_json` | **同一** `result_json` |
| 编排 | 独立 App | 独立 App；本仓库不把两者用边或工具调用连起来 |

调用方按入口选 App：有字走文本抽取，有图走本应用。本计划不实现编排、不把文本抽取发布为工具再嵌进来（跨工作区 `provider_type: workflow` 不可移植）。

**CONTEXT-MAP：** 不新增第四个 context。在「询价字段抽取」条下注明现有 DSL：意图识别、文本抽取、图片抽取。

---

## Tasks

### Task 0: 核对文件变量与 LLM vision schema

**Files:** 只读 `dify-docs` MCP、`$dify-workflow-dsl` 示例（含 LLM vision）、`references/node-schemas.md`

- [x] **Step 1:** 核对 `start` 单文件字段：`type: file`、`allowed_file_types` 仅 image、上传方式。按 skill 示例抄字段名，禁止臆造。
- [x] **Step 2:** 核对 LLM `vision.configs`（`detail` / `variable_selector`）及必填 `context` 块。
- [x] **Step 3:** 视觉模型 `name` 定为插件已列 `qwen3-vl-flash`（features 含 vision）；禁止编造 marketplace identity。
- [x] **Step 4:** 确认参数提取器 `query` 只能接文本；不要启用提取器 vision 代替 `read_image`。

### Task 1: 更新领域文档

**Files:**

- Modify: `CONTEXT.md`
- Modify: `CONTEXT-MAP.md`

- [x] **Step 1:** 增加「询价图片」「转写文本」；「询价文本」的 Avoid 与图片入口划清。
- [x] **Step 2:** CONTEXT-MAP 询价条列出三份 DSL 文件名。

### Task 2: 写 Workflow DSL

**Files:**

- Create: `dsl/workflows/inquiry_quote_extract_image.yml`

- [x] **Step 1:** 按图计划写 5 节点 4 边；`app.name` = `询价图片字段抽取`。
- [x] **Step 2:** `read_image` 只转写；`extract_fields` + `build_json` 从文本抽取复制并改 selector。
- [x] **Step 3:** `dependencies` 原样抄文本抽取。
- [x] **Step 4:** 自检：无密钥；`version: "0.7.0"` 有引号；节点 ID 无连字符；`end` 仅 `result_json`。

### Task 3: 严格校验

- [ ] **Step 1:** `python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_extract_image.yml`（本机无可用 python，导入前须补跑）
- [ ] **Step 2:** 失败则修 YAML 至 exit 0。
- [ ] **Step 3:** 交付说明：导入后重连模型凭据；确认工作区 tongyi 插件含 `qwen3-vl-flash` 且带 Vision；试跑一张真实询价截图。

**试跑期望（导入后人工）：**

| 样例 | 图内容（描述） | 期望 |
| --- | --- | --- |
| A | 邮件截图含「宁波海天贸易有限公司」「海运」「CIF」及港口 | `customer_name` 为公司名；`transport_mode=海运`；`trade_terms=CIF`；有公司名时即使图上有人名/邮箱也不用人名 |
| B | 仅签名「张三」+ 邮箱、`fuzzy_match_customer=0` | `customer_name` 空 |
| C | 同 B、`fuzzy_match_customer=1` | `customer_name` 为人名，无人名则为邮箱用户名 |
| D | 模糊/空白图 | 11 键均空值 + 置信低 + `supplement=""`，工作流成功 |
| E | 图含「尽量MSC直达 美西 周班」 | `supplement` 为一段文字，含船司MSC、航线美西、直达、船期周班；未写国家则不要出现国家片段 |

---

## 明确不做（YAGNI）

- 不做 Chatflow / 多轮 / Agent v2 / 独立 Agent App
- 不做 PDF、多图、文件列表、文档提取器 OCR
- 不在本 DSL 内调用文本抽取 App
- 不把转写文本作为 API 额外输出（除非后续明确要求）
- 不改 `inquiry_quote_extract.yml` 的图
- 不在未要求时提交 git commit

---

## Spec 覆盖自检

| 需求 | 对应 |
| --- | --- |
| 输入一张图片 | `start.inquiry_image`（file/image） |
| 功能与文本抽取相同 | 复制 extract + build_json；同一 `result_json`（含 `supplement`） |
| 补充信息一段文字 | 与文本抽取相同：同 pass 抽出后拼字符串，不新增 LLM |
| 有公司名优先公司名 | 沿用 `fuzzy_match_customer` 与 `build_json` 回退 |
| 不是真正的 Agent | Architecture：固定 Workflow |
| 与文本抽取解耦 | 独立 YAML，不改抽取图 |
