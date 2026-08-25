# 询价文本字段抽取工作流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成可导入 Dify 1.16 的 Workflow DSL：输入用户文字询价内容，结构化抽出客户、物流、港口、货品、服务与报价相关字段，并在流程终点严格输出一份含全部键的 JSON（缺省为空字符串）。

**Architecture:** 单次运行的 `workflow`（非 Chatflow）。图结构为 `start → parameter-extractor → code → end`。用[参数提取器](https://docs.dify.ai/zh/cloud/use-dify/nodes/parameter-extractor)抽取字段；再用 `code` 节点把全部业务字段装配成**固定键顺序的 JSON 对象字符串**（任一字段缺失一律写 `""`，禁止省略键、禁止 `null`）。不引入 Agent 节点。模型凭据与插件 identity 在目标工作区重连，DSL 内不写密钥。

**Tech Stack:** Dify App DSL `"0.7.0"`、`$dify-workflow-dsl`、`dify-docs` MCP、仓库校验器 `scripts/validate_dsl.py`。

## Global Constraints

- 目标：Dify 1.16.x / DSL `version: "0.7.0"`（必须加引号）
- 模式：`app.mode: workflow`
- 落盘：`dsl/workflows/inquiry_quote_extract.yml`
- 节点 ID：仅字母、数字、下划线，长度 1–50
- 禁止写入 API Key、credential ID、MCP URL、私有 dataset ID
- 终点必须输出严格 JSON：键集合与字段契约完全一致；缺省为 `""`；不得缺少任一键
- 交付前必须：`python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_extract.yml`
- 导入后须在目标工作区重连模型凭据后再试跑；禁止声称「导入即可运行」
- 生成时先查 `dify-docs` MCP，再用 `$dify-workflow-dsl`，对照 skill 示例与 `references/node-schemas.md` 中 `parameter-extractor` / `code` / `end`

---

## 字段契约（输出 schema）

| 业务字段 | 变量名 | 类型 | 取值约定 | 缺失时 |
| --- | --- | --- | --- | --- |
| 客户名称 | `customer_name` | string | 公司/客户名原文 | `""` |
| 物流类型 | `logistics_type` | string | 仅 `海运` 或 `空运`；无法判断留 `""` | `""` |
| 紧急程度 | `urgency_level` | string | 仅 `紧急` 或 `普通`；未提及默认 `普通` | `普通` |
| 起运港英文/代码 | `origin_port_en` | string | 如 `CNNGB` | `""` |
| 起运港中文 | `origin_port_zh` | string | 如 `宁波` | `""` |
| 目的港英文/代码 | `dest_port_en` | string | 如 `USLAX` | `""` |
| 目的港中文 | `dest_port_zh` | string | 如 `洛杉矶` | `""` |
| 货物品名 | `cargo_name` | string | 品名原文 | `""` |
| 货品规格 | `cargo_spec` | string | 如 `约1,200KG，6CBM` | `""` |
| 报价金额 | `quote_amount` | number | 浮点数，如 `1250.0`；去掉千分位逗号，只保留数值 | `0` |
| 货币单位 | `quote_currency` | string | 货币符号，如 `¥`、`$`、`€`；原文为 USD/CNY/RMB 等时归一为符号 | `""` |
| 报价条款 | `quote_terms` | string | 如 `EXW`、`CNF门到港`、`CIF`、`CFR` | `""` |
| 服务范围 | `service_scope` | string | 如 `订舱 / 起运港 THC / 目的港 THC`；多项用 ` / ` 连接 | `""` |

说明：

- 已删除原「是否紧急 / `is_urgent`」字段，改用「紧急程度 / `urgency_level`」。
- 用户示例「CNNGB/宁波」拆成英文/代码与中文两个字段；起运港、目的港各一对。
- 金额与币种拆开：`quote_amount` 为 number（浮点），`quote_currency` 为符号字符串（`¥` / `$` 等）。
- **严格 JSON 终态**：工作流最终对外只保证一份完整对象（见下方），键名、键数量固定为上表 **13** 个；字符串缺省 `""`，`urgency_level` 缺省 `"普通"`，`quote_amount` 缺省 `0`。

### 终点严格 JSON 形状（`result_json`）

`build_json` 节点必须输出字符串变量 `result_json`，内容为合法 JSON，键顺序建议固定为：

```json
{
  "customer_name": "",
  "logistics_type": "",
  "urgency_level": "普通",
  "origin_port_en": "",
  "origin_port_zh": "",
  "dest_port_en": "",
  "dest_port_zh": "",
  "cargo_name": "",
  "cargo_spec": "",
  "quote_amount": 0,
  "quote_currency": "",
  "quote_terms": "",
  "service_scope": ""
}
```

规则：

- 必须包含上述全部 13 个键，禁止增删键名。
- 禁止输出 `null`、禁止省略键；字符串空值一律 `""`；`urgency_level` 未给出时落成 `"普通"`；`quote_amount` 未给出或无法解析时落成 `0`（JSON number，非字符串）。
- `quote_amount` 在 JSON 中必须是 number（如 `1250.0`），不得写成 `"1250"`。
- `end` 至少输出 `result_json`；可选同时透出同名 13 个标量字段便于调试，但**验收以 `result_json` 为准**。

## 图计划

| 节点 ID | `data.type` | 输入 | 输出 |
| --- | --- | --- | --- |
| `start` | `start` | 表单变量 `inquiry_text`（paragraph，必填） | `inquiry_text` |
| `extract_fields` | `parameter-extractor` | `query: [start, inquiry_text]` | 上表全部 13 字段 + `__is_success` / `__reason` |
| `build_json` | `code` | 引用 `extract_fields` 全部业务字段 | `result_json`（string） |
| `end` | `end` | 引用 `build_json.result_json`（及可选标量） | `result_json`（必选） |

边：`start → extract_fields → build_json → end`（`sourceHandle: source`，`targetHandle: target`）。

参数提取器 `instruction` 要点（实施时写入 DSL）：

- 只从询价原文抽取，禁止臆造港口代码或金额。
- `logistics_type` 仅允许 `海运`/`空运`；同义表达（sea/air、海运整柜等）归一到二者之一。
- `urgency_level` 仅允许 `紧急`/`普通`；出现加急、紧急、ASAP、急单等为 `紧急`，否则 `普通`。
- `service_scope`：抽出订舱、起运港 THC、目的港 THC 等服务项；多项用 ` / ` 连接，保留业务原文用词。
- 港口：同时抽出代码/英文与中文；只有「CNNGB/宁波」这种合写时拆开；只有中文或只有代码时另一侧填 `""`。
- `quote_amount`：抽出纯数值为浮点数（去掉千分位与币种）；`quote_currency`：抽出或归一货币符号（`$`、`¥`、`€` 等；`USD`→`$`，`CNY`/`RMB`/`元`→`¥`，`EUR`→`€`；原文已是符号则原样）。
- `quote_terms` 保留业务原文写法（含「CNF门到港」），不要擅自改成标准 Incoterms 缩写 unless 原文已是缩写。
- 字符串字段原文未出现时输出 `""`；`urgency_level` 默认 `普通`；`quote_amount` 无法抽取时输出 `0`。

`build_json`（Python `main`）要点：

- 入参含 12 个字符串字段 + `quote_amount`（number，可空）。
- 字符串：`None` / 缺失 → `""`；`urgency_level` 仍为空 → `"普通"`。
- `quote_amount`：`None` / 空 / 非法 → `0`；合法则转为 `float`。
- `quote_currency`：缺失 → `""`。
- 用固定 13 键列表 `json.dumps(..., ensure_ascii=False)` 生成 `result_json`（确保 `quote_amount` 序列化为 JSON number）。
- 不抛错吞字段：即使上游某键为空也必须写入 JSON。

模型：DSL 中写占位 provider/name（与 skill 示例一致风格，如目标工作区常用模型）；`credential_ref` 为空；导入后重连。`reasoning_mode` 优先 `function_call`（模型支持时），否则 `prompt`。`vision.enabled: false`。

依赖：若模型来自 marketplace 插件，顶层 `dependencies` 只写已知 identity；未知则先不写假 identity，在交付说明里要求从工作区导出补全。

## 文件结构

| 路径 | 职责 |
| --- | --- |
| `docs/superpowers/plans/2026-08-25-inquiry-quote-extract.md` | 本计划（已更新） |
| `dsl/workflows/inquiry_quote_extract.yml` | 待生成的可导入 Workflow DSL |
| `scripts/validate_dsl.py` | 已有校验入口，不改逻辑 |

不新增应用代码、不写测试代码（本仓库只产 DSL；验证靠严格校验 + 人工导入试跑）。

---

### Task 1: 用 MCP 核对参数提取器、code 与 end 输出写法

**Files:**

- 只读：`dify-docs` MCP、`~/.cursor/skills/dify-workflow-dsl/references/node-schemas.md`
- 不修改仓库文件

**Interfaces:**

- Consumes: 本字段契约、图计划、严格 JSON 终态要求
- Produces: 确认 `parameter-extractor`（含 `number` 类型参数）、`code`（`def main` / `outputs`）、`end.outputs` selector 形状，供 Task 2 写 YAML

- [ ] **Step 1: 查官方文档**

用 `search_dify_docs`（language=`zh`）查「参数提取器」「代码执行」「输出」，再用 `query_docs_filesystem_dify_docs` 阅读对应 `.mdx`。确认：提取字段作为节点输出；code 可返回字符串；end 可暴露 `result_json`。

- [ ] **Step 2: 对照 skill schema**

打开 `references/node-schemas.md` 的 `parameter-extractor`、`code`、`end` 片段，记下实施时必须带的键。

- [ ] **Step 3: 记录工作区假设**

在回复中写明：默认模型占位符准备用什么（例如 tongyi/openai 之一）；若用户未提供工作区导出，`dependencies` 策略为「有证据才写」。

---

### Task 2: 生成 Workflow DSL YAML

**Files:**

- Create: `dsl/workflows/inquiry_quote_extract.yml`

**Interfaces:**

- Consumes: Task 1 确认的节点写法；本计划字段契约、严格 JSON 终态与图计划
- Produces: 完整 `kind: app` / `mode: workflow` DSL，四节点连通，`end` 必含 `result_json`

- [ ] **Step 1: 调用 skill 生成**

显式使用 `$dify-workflow-dsl`，目标 DSL `0.7.0`，模式 `workflow`。按图计划写节点 ID：`start`、`extract_fields`、`build_json`、`end`。

`start.variables` 唯一项：

```yaml
- label: "询价内容"
  variable: inquiry_text
  type: paragraph
  required: true
  max_length: 10000
```

`extract_fields.parameters` 必须覆盖字段契约中全部 **13** 个业务变量；除 `quote_amount` 的 `type: number` 外，其余 `type: string`；均带 `name` / `description` / `required: false`。**不得**再出现 `is_urgent`。必须含 `quote_currency`。

- [ ] **Step 2: 实现 `build_json` 与 edges / end**

边语义：`start → extract_fields → build_json → end`。

`build_json`：Python `def main(...)`，输出键 `result_json`（string），严格按「终点严格 JSON 形状」装配 13 键（`quote_amount` 为 float）。

`end.outputs` 至少包含：

```yaml
- variable: result_json
  value_selector: [build_json, result_json]
```

可选再透出 13 个标量；验收以 `result_json` 为准。不要输出密钥类字段。

- [ ] **Step 3: 自检清单（写入前）**

- `version: "0.7.0"` 有引号  
- 无连字符节点 ID  
- 无 `is_urgent`  
- 含 `urgency_level`、`service_scope`、`quote_currency`  
- `quote_amount` 为 number，终态 JSON 中为浮点而非字符串  
- `result_json` 路径贯通到 `end`  
- 无 API Key / credential 实值  
- LLM/提取器无多余臆造插件 identity  

---

### Task 3: 严格校验并给出导入说明

**Files:**

- Modify: 仅当校验失败时改 `dsl/workflows/inquiry_quote_extract.yml`
- Test: 通过 `scripts/validate_dsl.py`

**Interfaces:**

- Consumes: Task 2 产出的 YAML
- Produces: 校验通过的 YAML + 导入后手工步骤列表

- [ ] **Step 1: 跑严格校验**

```text
python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_extract.yml
```

Expected: exit code `0`，无 error/warning（strict 下 warning 也失败）。

- [ ] **Step 2: 若失败则按诊断修 YAML**

只修校验器指出的结构问题（边、selector、必填块等），不扩大需求范围。

- [ ] **Step 3: 交付说明（回复用户，不写 README）**

必须包含：

1. 文件路径 `dsl/workflows/inquiry_quote_extract.yml`
2. 在 Dify 1.16 工作区导入 DSL
3. 重连参数提取器所用模型凭据
4. 用样例询价试跑（见下方样例），核对 `outputs.result_json` 含全部 13 键，且 `quote_amount` 为 JSON number
5. 明确：静态校验通过 ≠ 业务抽取准确；准确率依赖模型与 instruction

**试跑样例输入（可直接贴进 `inquiry_text`）：**

```text
客户：宁波海天贸易有限公司
走海运，普通时效。起运 CNNGB/宁波，目的 USLAX/洛杉矶。
货名：塑料配件。规格约1,200KG，6CBM。
服务：订舱 / 起运港 THC / 目的港 THC。
报价 USD 1,250，条款 CIF。
```

**期望 `result_json`（人工对照，键必须齐全）：**

```json
{
  "customer_name": "宁波海天贸易有限公司",
  "logistics_type": "海运",
  "urgency_level": "普通",
  "origin_port_en": "CNNGB",
  "origin_port_zh": "宁波",
  "dest_port_en": "USLAX",
  "dest_port_zh": "洛杉矶",
  "cargo_name": "塑料配件",
  "cargo_spec": "约1,200KG，6CBM",
  "quote_amount": 1250.0,
  "quote_currency": "$",
  "quote_terms": "CIF",
  "service_scope": "订舱 / 起运港 THC / 目的港 THC"
}
```

---

## 明确不做（YAGNI）

- 不做 Chatflow / 多轮澄清
- 不做 Agent v2 / 知识库 / HTTP 回写业务系统
- 不做港口代码权威校验表（无知识库时禁止编造标准码）
- 不恢复 `is_urgent` 字段
- 不在本计划阶段提交 git commit（除非用户另要求）

## Spec 覆盖自检

| 需求 | 对应任务 |
| --- | --- |
| 客户名称 | Task 2 字段 `customer_name` |
| 物流类型 海运/空运 | Task 2 `logistics_type` + instruction |
| 紧急程度 紧急/普通 | Task 2 `urgency_level` + instruction |
| 删除是否紧急 | 契约与 Task 2 禁止 `is_urgent` |
| 服务范围 | Task 2 `service_scope` |
| 起运/目的港中英文字段 | Task 2 四个 port 字段 |
| 货物品名 / 规格 | Task 2 `cargo_name` / `cargo_spec` |
| 报价金额浮点 + 货币符号 | Task 2 `quote_amount`（number）/ `quote_currency` |
| 报价条款 | Task 2 `quote_terms` |
| 终点严格 JSON、全字段；字符串空则 `""`，金额空则 `0` | `build_json` + `end.result_json` |
| 先写计划不实施 | 本文件已落盘；Task 1–3 待用户下令执行 |
