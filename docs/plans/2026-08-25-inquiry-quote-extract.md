# 询价文本字段抽取工作流 Implementation Plan

> **For agentic workers:** 按 Task 顺序逐步实施本计划；使用 checkbox（`- [ ]` / `- [x]`）跟踪进度。实施时显式使用 `$dify-workflow-dsl` skill。

**Goal:** 生成可导入 Dify 1.16 的 Workflow DSL：输入客户**询价文本**，结构化抽出客户、物流、港口、货品、服务与条款相关字段，并在流程终点严格输出一份含全部键的 JSON（字符串缺省 `""`）。

**Architecture:** 单次运行的 `workflow`（非 Chatflow）。图结构为 `start → parameter-extractor → code → end`。用[参数提取器](https://docs.dify.ai/zh/cloud/use-dify/nodes/parameter-extractor)抽取字段；再用 `code` 节点把全部业务字段装配成**固定键顺序的 JSON 对象字符串**（禁止省略键、禁止 `null`）。提取失败时仍输出完整 11 键空壳。不引入 Agent 节点。模型凭据与插件 identity 在目标工作区重连，DSL 内不写密钥。对外验收以 API `outputs.result_json` 为准，不要求 Web 端并排展示标量。

**Tech Stack:** Dify App DSL `"0.7.0"`、`$dify-workflow-dsl`、`dify-docs` MCP、仓库校验器 `scripts/validate_dsl.py`。

**Domain docs（grilling 已对齐）：** 读 `CONTEXT.md` 与 `docs/adr/0001-first-occurrence-wins.md`、`0003-empty-urgency-when-unspecified.md`。

## Global Constraints

- 目标：Dify 1.16.x / DSL `version: "0.7.0"`（必须加引号）
- 模式：`app.mode: workflow`
- 落盘：`dsl/workflows/inquiry_quote_extract.yml`
- 节点 ID：仅字母、数字、下划线，长度 1–50
- 禁止写入 API Key、credential ID、MCP URL、私有 dataset ID
- 终点必须输出严格 JSON：键集合与字段契约完全一致；不得缺少任一键
- 单值冲突策略：**取文本中先出现的那个**（公司名、物流类型、条款）；见 ADR-0001
- 交付前必须：`python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_extract.yml`
- 导入后须在目标工作区重连模型凭据后再试跑；禁止声称「导入即可运行」
- 生成时先查 `dify-docs` MCP，再用 `$dify-workflow-dsl`，对照 skill 示例与 `references/node-schemas.md` 中 `parameter-extractor` / `code` / `end`

---

## 字段契约（输出 schema）

| 业务字段 | 变量名 | 类型 | 取值约定 | 缺失时 |
| --- | --- | --- | --- | --- |
| 客户名称 | `customer_name` | string | 文本中**最先出现**的公司名（运营方为物流公司，接受该策略） | `""` |
| 物流类型 | `logistics_type` | string | 仅 `海运`、`空运` 或 `陆运`；同时出现取先出现；无法判断留 `""` | `""` |
| 紧急程度 | `urgency_level` | string | 仅 `紧急` 或 `普通`；未提及为 `""`；冲突时任一紧急信号则 `紧急` | `""` |
| 起运地英文/代码 | `origin_port_en` | string | 如 `CNNGB`；禁止臆造 | `""` |
| 起运地中文 | `origin_port_zh` | string | 城市/地区地名，如 `宁波`；去掉「港」后缀；禁止臆造 | `""` |
| 目的地英文/代码 | `dest_port_en` | string | 如 `USLAX`；禁止臆造 | `""` |
| 目的地中文 | `dest_port_zh` | string | 城市/地区地名，如 `洛杉矶`；去掉「港」后缀；禁止臆造 | `""` |
| 货物品名 | `cargo_name` | string | 品名原文 | `""` |
| 货品规格 | `cargo_spec` | string | 如 `约1,200KG，6CBM` | `""` |
| 报价条款 | `quote_terms` | string | 多条款时只取**第一个**条款词；不擅自标准化缩写 | `""` |
| 服务范围 | `service_scope` | string | 原文服务项；多项用 ` / ` 连接 | `""` |

说明：

- 输入是客户**询价文本**（可能尚无报价）；**不抽取金额与币种**（已从契约移除）。
- 已删除「是否紧急 / `is_urgent`」及 `quote_amount` / `quote_currency`。
- 「CNNGB/宁波」拆成英文/代码与中文；起运地、目的地各一对；中文侧不带「港」；只填原文出现的一侧。
- **严格 JSON 终态**：11 键固定；字符串缺省 `""`（含 `urgency_level`）。

### 终点严格 JSON 形状（`result_json`）

`build_json` 节点必须输出字符串变量 `result_json`，内容为合法 JSON，键顺序建议固定为：

```json
{
  "customer_name": "",
  "logistics_type": "",
  "urgency_level": "",
  "origin_port_en": "",
  "origin_port_zh": "",
  "dest_port_en": "",
  "dest_port_zh": "",
  "cargo_name": "",
  "cargo_spec": "",
  "quote_terms": "",
  "service_scope": ""
}
```

规则：

- 必须包含上述全部 11 个键，禁止增删键名。
- 禁止输出 `null`、禁止省略键。
- `__is_success=0` 或上游全空时，仍输出上表空壳（ADR-0003）。
- `end` **只需**输出 `result_json`（验收标准）；不要依赖标量并排展示。

## 图计划

| 节点 ID | `data.type` | 输入 | 输出 |
| --- | --- | --- | --- |
| `start` | `start` | 表单变量 `inquiry_text`（paragraph，必填） | `inquiry_text` |
| `extract_fields` | `parameter-extractor` | `query: [start, inquiry_text]` | 上表全部 11 字段 + `__is_success` / `__reason` |
| `build_json` | `code` | 引用 `extract_fields` 全部业务字段 | `result_json`（string） |
| `end` | `end` | 引用 `build_json.result_json` | `result_json`（必选） |

边：`start → extract_fields → build_json → end`（`sourceHandle: source`，`targetHandle: target`）。

参数提取器 `instruction` 要点（实施时写入 DSL）：

- 输入是客户询价原文；只抽取、禁止臆造港口代码/译名。
- `customer_name`：取最先出现的公司名。
- `logistics_type` 仅 `海运`/`空运`/`陆运`；同义归一（陆运/汽运/卡车/公路运输/land/trucking→陆运）；同时出现取先出现。
- `urgency_level` 仅 `紧急`/`普通`；未提及输出空；出现加急/紧急/ASAP/急单等为 `紧急`；与「不急」并存时仍取 `紧急`；仅有普通/不急等信号则为 `普通`。
- `service_scope`：原文服务项，多项用 ` / ` 连接。
- 起运地/目的地：`origin_port_en` / `dest_port_en` 为英文名或 UN/LOCODE；`origin_port_zh` / `dest_port_zh` 为中文地名（去掉「港」后缀）；合写「CNNGB/宁波」或分行并列都拆开；「A → B」前起运后目的；陆运场景同样适用；只出现一侧则另一侧 `""`；禁止补全未出现的代码或译名。
- `quote_terms`：多条款只取第一个条款词。
- 字符串未出现 → `""`。

`build_json`（Python `main`）要点：

- 入参含 11 个字符串字段。
- 字符串：`None` / 缺失 → `""`；**不要**把空的 `urgency_level` 改成 `"普通"`。
- 用固定 11 键 `json.dumps(..., ensure_ascii=False)` 生成 `result_json`。
- 上游失败或全空也必须写出完整 JSON 对象字符串。

模型：DSL 中写占位 provider/name；`credential_ref` 为空；导入后重连。`reasoning_mode` 优先 `function_call`，否则 `prompt`。`vision.enabled: false`。

依赖：有证据才写 marketplace identity；未知则交付说明要求从工作区导出补全。

## 文件结构

| 路径 | 职责 |
| --- | --- |
| `docs/plans/2026-08-25-inquiry-quote-extract.md` | 本计划 |
| `CONTEXT.md` | 领域 glossary |
| `docs/adr/0001-*.md` … `0003-*.md` | grilling 决策 |
| `dsl/workflows/inquiry_quote_extract.yml` | Workflow DSL |
| `scripts/validate_dsl.py` | 校验入口 |

不新增应用代码、不写测试代码（本仓库只产 DSL；验证靠严格校验 + 人工导入试跑）。

---

### Task 1: 用 MCP 核对参数提取器、code 与 end 输出写法

**Files:**

- 只读：`dify-docs` MCP、`~/.cursor/skills/dify-workflow-dsl/references/node-schemas.md`、`CONTEXT.md`、相关 ADR
- 不修改仓库文件

**Interfaces:**

- Consumes: 本字段契约、图计划、严格 JSON 终态要求
- Produces: 确认 `parameter-extractor`、`code`、`end.outputs` 形状

- [x] **Step 1: 查官方文档**

用 `search_dify_docs`（language=`zh`）查「参数提取器」「代码执行」「输出」，再 `query_docs_filesystem_dify_docs` 读对应 `.mdx`。

- [x] **Step 2: 对照 skill schema**

打开 `references/node-schemas.md` 的 `parameter-extractor`、`code`、`end`。

- [x] **Step 3: 记录工作区假设**

写明模型占位符策略；`dependencies` 有证据才写。

---

### Task 2: 生成 Workflow DSL YAML

**Files:**

- Create: `dsl/workflows/inquiry_quote_extract.yml`

**Interfaces:**

- Consumes: Task 1；本计划与 `CONTEXT.md`
- Produces: 完整 DSL，四节点连通，`end` 仅含 `result_json`

- [x] **Step 1: 调用 skill 生成**

显式使用 `$dify-workflow-dsl`，DSL `0.7.0`，`workflow`。节点 ID：`start`、`extract_fields`、`build_json`、`end`。

```yaml
- label: "询价内容"
  variable: inquiry_text
  type: paragraph
  required: true
  max_length: 10000
```

`extract_fields.parameters` 覆盖全部 **11** 变量，均为 `string`；无 `is_urgent`、无 `quote_amount` / `quote_currency`。

- [x] **Step 2: 实现 `build_json` 与 edges / end**

边：`start → extract_fields → build_json → end`。`build_json` 输出 `result_json`。`end.outputs` 仅：

```yaml
- variable: result_json
  value_selector: [build_json, result_json]
```

- [x] **Step 3: 自检清单（写入前）**

- `version: "0.7.0"` 有引号  
- `urgency_level` 缺省为空，不默认普通  
- instruction 含「先出现」与紧急冲突规则  
- `logistics_type` 支持 `陆运`  
- `result_json` 贯通到 `end`  
- 无密钥 / 无臆造插件 identity  

---

### Task 3: 严格校验并给出导入说明

**Files:**

- Modify: 仅校验失败时改 YAML
- Test: `scripts/validate_dsl.py`

- [x] **Step 1: 跑严格校验**

```text
python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_extract.yml
```

Expected: exit code `0`。

- [x] **Step 2: 若失败则按诊断修 YAML**

- [x] **Step 3: 交付说明**

含路径、导入、重连凭据、样例试跑、静态校验≠业务准确。

**试跑样例输入（海运）：**

```text
客户：宁波海天贸易有限公司
走海运，普通时效。起运 CNNGB/宁波，目的 USLAX/洛杉矶。
货名：塑料配件。规格约1,200KG，6CBM。
服务：订舱 / 起运港 THC / 目的港 THC。
条款 CIF。
```

**期望 `result_json`：**

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
  "quote_terms": "CIF",
  "service_scope": "订舱 / 起运港 THC / 目的港 THC"
}
```

（本样例含「普通时效」，故 `urgency_level` 为 `普通`；若删去时效措辞则应为 `""`。）

**试跑样例输入（陆运）：**

```text
客户：苏州恒达机电有限公司
走陆运，汽运至上海。货名：电机配件，约 800KG。
```

**期望输出：**

- `logistics_type`：`"陆运"`（「汽运」等同义应归一为陆运）
- `dest_port_zh`：`"上海"`（不带「港」）

---

## 明确不做（YAGNI）

- 不做 Chatflow / 多轮澄清
- 不做 Agent v2 / 知识库 / HTTP 回写
- 不做港口代码补全表
- 不恢复 `is_urgent`；不抽取金额/币种；不扩多值报价数组
- 不在未要求时提交 git commit

## Spec 覆盖自检

| 需求 | 对应 |
| --- | --- |
| 询价文本输入 | `inquiry_text` + CONTEXT |
| 先出现策略 | ADR-0001 + instruction |
| 紧急缺省空 / 冲突偏紧急 | ADR-0003 + instruction |
| 陆运支持 | `logistics_type` + instruction |
| 服务 ` / ` | `service_scope` |
| 仅 `result_json` 验收 | `end` |
| 提取失败仍出空壳 | `build_json` |
| Task 1–3 已执行 | `dsl/workflows/inquiry_quote_extract.yml` |
