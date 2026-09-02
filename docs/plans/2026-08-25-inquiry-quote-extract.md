# 询价文本字段抽取工作流 Implementation Plan

> **For agentic workers:** 按 Task 顺序逐步实施本计划；使用 checkbox（`- [ ]` / `- [x]`）跟踪进度。实施时显式使用 `$dify-workflow-dsl` skill。

**Goal:** 生成可导入 Dify 1.16 的 Workflow DSL：输入客户**询价文本**，结构化抽出客户、运输方式、**起运/目的地（含各类地点代码）**、货品、服务与条款相关字段；**每个字段附带置信度**；流程终点严格输出含全部键的 JSON（值 + 置信度双层结构，字符串缺省 `""`、置信度缺省 `置信低`）。

**Architecture（v2 修订）：** 单次运行的 `workflow`（非 Chatflow）。图结构仍为 `start → parameter-extractor → code → end`。**不新增第二个 LLM 节点**——在现有参数提取器单次调用中同步产出字段值与置信度；`code` 节点负责枚举校验、置信度降级与 JSON 装配。详见下文「置信度设计决策」。

**Tech Stack:** Dify App DSL `"0.7.0"`、`$dify-workflow-dsl`、`dify-docs` MCP、仓库校验器 `scripts/validate_dsl.py`。

**Domain docs（grilling 已对齐，v2 待同步）：** 读 `CONTEXT.md` 与 `docs/adr/0001-first-occurrence-wins.md`、`0003-empty-urgency-when-unspecified.md`（紧急程度枚举与 ADR-0003 需随 v2 修订）。

---

## v2 变更摘要（相对已交付 v1）

| 项 | v1 | v2 |
| --- | --- | --- |
| 运输方式字段 | `logistics_type`：`海运`/`空运`/`陆运` | `transport_mode`：7 档封闭枚举（见下表） |
| 贸易条款字段 | `quote_terms`：原文第一个条款词 | `trade_terms`：12 个 Incoterms 缩写封闭枚举 |
| 紧急程度 | `urgency_level`：`紧急`/`普通` | `urgency_level`：`普通`/`加急`（**Breaking**：`紧急` 归一为 `加急`） |
| 输出形状 | 11 键平铺字符串 | 11 键，每键 `{ value, confidence }` |
| 图结构 | 4 节点 | 仍为 4 节点（不增 LLM） |

**Breaking change：** API 消费方若已对接 v1 的 `result_json` 平铺结构，须同步升级解析逻辑。

---

## Global Constraints

- 目标：Dify 1.16.x / DSL `version: "0.7.0"`（必须加引号）
- 模式：`app.mode: workflow`
- 落盘：`dsl/workflows/inquiry_quote_extract.yml`
- 节点 ID：仅字母、数字、下划线，长度 1–50
- 禁止写入 API Key、credential ID、MCP URL、私有 dataset ID
- 终点必须输出严格 JSON：键集合与字段契约完全一致；不得缺少任一键
- 单值冲突策略：**取文本中先出现的那个**（公司名、运输方式、贸易条款）；见 ADR-0001
- 交付前必须：`python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_extract.yml`
- 导入后须在目标工作区重连模型凭据后再试跑；禁止声称「导入即可运行」
- 生成时先查 `dify-docs` MCP，再用 `$dify-workflow-dsl`，对照 skill 示例与 `references/node-schemas.md` 中 `parameter-extractor` / `code` / `end`

---

## 字段契约（输出 schema）

### 业务字段

| 业务字段 | 变量名 | 类型 | 取值约定 | 缺失时 `value` |
| --- | --- | --- | --- | --- |
| 客户名称 | `customer_name` | string | 文本中**最先出现**的公司名 | `""` |
| 运输方式 | `transport_mode` | string | **仅**下表 7 值；同义归一后映射；无法判断 `""` | `""` |
| 紧急程度 | `urgency_level` | string | **仅** `普通` 或 `加急`；未提及 `""` | `""` |
| 起运地英文/代码 | `origin_port_en` | string | 原文出现的**英文或标准代码**（见下节）；**有英文/代码时优先填本侧**；禁止臆造 | `""` |
| 起运地中文 | `origin_port_zh` | string | 原文中文地名；去掉交通设施后缀（港/机场/站等） | `""` |
| 目的地英文/代码 | `dest_port_en` | string | 同 `origin_port_en`，角色为目的地 | `""` |
| 目的地中文 | `dest_port_zh` | string | 同 `origin_port_zh`，角色为目的地 | `""` |
| 货物品名 | `cargo_name` | string | 品名原文 | `""` |
| 货品规格 | `cargo_spec` | string | 规格原文 | `""` |
| 贸易条款 | `trade_terms` | string | **仅**下表 12 值；多条款取**第一个**可映射条款 | `""` |
| 服务范围 | `service_scope` | string | 原文服务项；多项用 ` / ` 连接 | `""` |

### 封闭枚举（`code` 节点须硬校验）

**运输方式 `transport_mode`（仅此 7 值，大小写与空格须完全一致）：**

`海运 FCL`、`海运 LCL`、`空运`、`铁路`、`公路`、`快递`、`多式联运`

同义归一指引（写入 `extract_fields.instruction`，实施时细化）：

| 原文信号（示例） | 归一结果 |
| --- | --- |
| FCL、整箱、海运整箱、full container | `海运 FCL` |
| LCL、拼箱、海运拼箱、less than container | `海运 LCL` |
| 海运（未区分 FCL/LCL）、ocean、sea freight | 无法区分时 `""`（**禁止**臆猜 FCL/LCL） |
| 空运、air freight、航空 | `空运` |
| 铁路、铁运、rail | `铁路` |
| 公路、汽运、卡车、陆运、trucking、land | `公路` |
| 快递、特快、express、courier | `快递` |
| 多式联运、海铁、海空、联运 | `多式联运` |

**贸易条款 `trade_terms`（仅此 12 值，大写）：**

`EXW`、`FCA`、`CPT`、`CIP`、`DAP`、`DPU`、`DDP`、`FAS`、`FOB`、`CFR`、`CIF`

- 多条款并存：取文本中**最先出现**的可识别条款（延续 ADR-0001）。
- 原文为小写或带标点（如 `cif.`）→ 归一为大写枚举；无法映射 → `value=""`。

**紧急程度 `urgency_level`（仅此 2 值）：**

`普通`、`加急`

- 未提及 → `""`（延续 ADR-0003，**不**默认 `普通`）。
- `紧急`、`加急`、`ASAP`、`急单` 等 → `加急`。
- `普通`、`不急`、`正常时效` 等 → `普通`。
- 冲突：任一加急信号则 `加急`（延续 v1 冲突偏急策略，枚举值改为 `加急`）。

### 起运地 / 目的地与地点代码（多运输方式）

JSON 键名仍为 `origin_port_*` / `dest_port_*`（v1 延续，**不表示仅限港口**）。语义为：**起运/目的地点**的代码侧（`_*_en`）与中文侧（`_*_zh`），与 `transport_mode` **联动识别、分侧填写**，但**不因运输方式臆造未出现的代码**。

#### `_*_en` 英文/代码优先原则

`origin_port_en` / `dest_port_en` 统一收录**拉丁字符**形式的地点标识；**能用英文（或国际通用代码）的尽量填入本侧**，中文地名填入 `_*_zh`。

| 优先级 | 填入 `_*_en` | 填入 `_*_zh` |
| --- | --- | --- |
| 1 | 原文同时有中英文/代码 → **标准代码或英文**进 en，中文进 zh | 对应中文地名 |
| 2 | 原文仅英文或仅代码 | en 有值，zh 为 `""` |
| 3 | 原文仅中文、无任何拉丁标识 | en 为 `""`，zh 有值 |

- **允许**：从合写格式拆出英文/代码侧（`VNP/北京南`、`Beijing South/北京南`）。
- **禁止**：仅中文时翻译或补全英文（如仅「成都南」→ **不得**填 `Chengdu South`）；禁止跨码制推导（`CNNGB`→`宁波` 可拆 zh，不得反向）。

#### 代码侧 `origin_port_en` / `dest_port_en` 收录范围

按运输方式，原文出现下列任一类即填入 en 侧（**原样保留**拉丁字符形态，禁止跨体系转换）：

| 运输方式 | 典型英文/代码标识 | 示例 |
| --- | --- | --- |
| 海运 FCL / 海运 LCL | UN/LOCODE（通常 5 位字母）、英文港口/码头/城市名 | `CNNGB`、`USLAX`、`Ningbo`、`Los Angeles` |
| 空运 | IATA 三字机场码、英文机场/城市名 | `PVG`、`CAN`、`LAX`、`Shanghai Pudong` |
| 铁路 | **铁路电报码**（国铁常用 3 位字母）、**UIC 位置码**（国际铁路 7 位数字，原文出现才填）、**英文站名**、**拼音/罗马化站名**（原文出现才填） | `VNP`（北京南）、`EAY`（西安北）、`8600652`（UIC，若原文写出）、`Beijing South`、`Xi'an North`、`Chengdu South` |
| 公路 / 快递 | 英文城市/区县名、邮编、门点英文地址片段 | `Suzhou`、`Pudong`、`Shanghai`、`200120` |
| 多式联运 | 各段按原文实际标识；可异构（起运港口码 + 目的机场码 / 铁路码） | `CNNGB` + `FRA`；`VNP` + `LAX` |

铁路补充说明：

- 铁路**有**英文与国际代码体系，与海运/空运一样应优先识别进 `_*_en`；并非「铁路只有中文」。
- 国铁**电报码**（3 位字母）与**英文站名**在跨境/铁路联运询价中较常见，原文写出即填 en 侧。
- **UIC 码**、**拼音站名**仅在原文出现时填写；不要根据中文站名查表补码。
- 合写 `VNP/北京南`、`Beijing South/北京南`、`成都南(CNW)` 等 → en 取代码或英文，zh 取中文站名（去「站」等后缀）。

规则：

- **只填原文出现的**英文/代码；禁止由纯中文翻译补英文、禁止由一种码制推导另一种。
- 合写 `代码/中文`、`英文/中文`、`代码（中文）` → 拆到 en / zh 两侧；**en 侧取代码或英文，zh 侧取中文**。
- 路线表达「A → B」「A to B」「从 A 到 B」「A 发 B 收」→ A 为起运、B 为目的；每侧独立拆 en/zh。
- 仅中文、无拉丁标识 → en 侧 `""`；仅英文/代码、无中文 → zh 侧 `""`。
- `transport_mode` 与地点类型**不一致时不强行纠正**（如写了空运但给港口码）：仍按原文填，置信度降为 `置信中` 或 `置信低`（见置信度表）。
- 不要把公司名、货号、柜号、提单号误填入地点字段。

#### 中文侧 `origin_port_zh` / `dest_port_zh` 收录范围

| 场景 | 填写 | 后缀处理 |
| --- | --- | --- |
| 海运港口 | 港口所在城市/地区名 | `宁波港`→`宁波` |
| 空运 | 机场所在城市或原文地名 | `浦东机场`→`浦东`；`上海浦东国际机场`→按原文最短合理地名 `浦东` 或 `上海`（与原文一致优先） |
| 铁路 | 站所在城市或站名 | `北京南站`→`北京南`；`郑州站`→`郑州` |
| 公路/快递 | 城市、区县、乡镇 | `昆山市`→`昆山`；`送至上海`→`上海` |
| 门点地址 | 取原文中的**最小可识别地名**（市/区/县），不扩写完整地址 | `苏州工业园区`→`苏州工业园区`（原文子串） |

- 去掉后缀仅当原文含交通设施词：`港`、`机场`、`国际机场`、`站`、`火车站`、`高铁站`；**不**去掉行政区划词（市、区、县）。
- 禁止根据 en/代码侧反推中文。

#### 与 `transport_mode` 联动（instruction 要点）

| 情况 | 处理 |
| --- | --- |
| 已识别 `transport_mode` 且原文地点表述单一 | 按上表理解代码类型，正常抽取 |
| 未识别 `transport_mode`（`""`） | 仍可从原文抽地点；代码类型按**原文形态**判断（3 位大写→倾向 IATA，5 位→倾向 UN/LOCODE），**不**因形态猜测而改写 value |
| 多式联运且起运/目的代码类型不同 | 各侧独立填写，允许起运 `CNNGB` + 目的 `PVG` |
| 公路/快递仅中文门点 | zh 有值；en 为 `""`（**不**把「上海」译成 `Shanghai`） |
| 铁路原文含电报码/英文站名 | en 填代码或英文，zh 填中文（合写则拆分） | 
| 铁路原文仅中文站名 | zh 有值；en 为 `""` |

**结论：可以一起识别。** 同一套四字段（`origin_port_en/zh`、`dest_port_en/zh`）覆盖海运/空运/铁路/公路/快递/多式联运；差异体现在原文出现何种标识，而非拆成多套字段。`code` 节点**不**校验地点码制白名单（避免误杀 IATA/铁路码），只做 strip、中文后缀规范化与空值降级。

---

### 置信度（每字段必有）

| 属性 | 变量后缀 | 类型 | 允许值 | 缺省 |
| --- | --- | --- | --- | --- |
| 置信度 | `{field}_confidence`（提取器输出）→ 装配进 `confidence` 键 | string | `置信高`、`置信中`、`置信低` | `置信低` |

#### 全局等级定义

| 等级 | 含义 |
| --- | --- |
| 置信高 | 原文有**直接、无歧义**依据；或封闭枚举值在原文中**完整出现**（含大小写/空格归一后等价） |
| 置信中 | 经同义归一、格式拆分、上下文推断或冲突消解得到，语义合理但非原文逐字对应 |
| 置信低 | `value` 为空；无法从原文判断；字段间角色混淆；`code` 校验清空或强制降级 |

#### 逐字段置信度规则（写入 `extract_fields.instruction` + `code` 兜底）

实施时**每个字段独立判定**，不得用全局默认值代替字段级判断。

| 字段 | 置信高 | 置信中 | 置信低 |
| --- | --- | --- | --- |
| `customer_name` | 原文出现带公司后缀的完整名称（如「××有限公司」）；或「客户：」「公司：」等标签后紧邻的名称与输出一致 | 首段/首行出现的机构名但无明确标签；或去掉「客户：」前缀后与原文子串匹配 | `value=""`；仅有人名、部门、品牌而无公司主体；多个公司名且「先出现」规则无法适用；从货代/承运商签名推断而非询价方 |
| `transport_mode` | 原文完整出现七档枚举之一（如「海运 FCL」「空运」） | 同义归一得到（如 `FCL`→`海运 FCL`、`汽运`→`公路`、`航空`→`空运`）；一文多种运输方式但已按**先出现**取定 | `value=""`；仅写「海运」未区分 FCL/LCL；多种方式并存且先后顺序不明；枚举外被 `code` 清空 |
| `urgency_level` | 原文直接出现「普通」或「加急」 | 同义归一（`紧急`/`急单`/`ASAP`→`加急`，`不急`/`正常时效`→`普通`）；加急与普通信号**冲突**后取 `加急`（值对、置信为中） | `value=""`（未提及任何时效信号）；信号极其模糊无法归到两档；枚举外被 `code` 清空 |
| `origin_port_en` | 原文直接出现 UN/LOCODE、IATA、铁路电报码/UIC、英文站名/城市名/邮编等，与输出一致 | 从合写格式拆出 en 侧（优先代码或英文）；从路线表达推断起运侧且标识在原文 | `value=""`；由纯中文翻译补英文；跨码制补全；与 `dest_port_en` 混淆 |
| `origin_port_zh` | 原文直接出现中文地名，去交通设施后缀后与输出一致 | 从合写格式拆出中文侧；从「从××出发」推断起运；仅去后缀 | `value=""`；由 en/代码翻译；与目的地混淆；后缀未去掉 |
| `dest_port_en` | 同 `origin_port_en`，目的地侧 | 同 `origin_port_en`，从路线表达推断目的地 B 侧 | 同 `origin_port_en` 低置信情形 |
| `dest_port_zh` | 同 `origin_port_zh`，目的地侧 | 从「送至××」「到××」等推断目的地 | 同 `origin_port_zh` 低置信情形 |
| `cargo_name` | 原文有「货名」「品名」「货物」等标签且输出与标签后内容一致；或货名为独立名词短语且与规格明确分离 | 从叙述句中抽出货物描述（无标签）；货名与规格在同句但已正确拆分 | `value=""`；与 `cargo_spec` 混填（如把「约 800KG」写入货名）；将服务项/条款误作货名 |
| `cargo_spec` | 原文明确出现重量/体积/件数/尺寸等量化描述（如 `1,200KG`、`6CBM`、`100件`）且与输出一致 | 规格嵌在货描句中但已正确抽出；单位或标点做了轻微规范化 | `value=""`；只有模糊描述（「一批货」「大量」）无可量化信息；与货名未拆分 |
| `trade_terms` | 原文直接出现 12 档 Incoterms 之一（大小写不敏感，如 `CIF`、`cif.`） | 小写/标点/括号归一后映射（`（CIF）`→`CIF`）；多条款并存但已取**最先出现**的可映射条款 | `value=""`；条款非 Incoterms 12 档；多条款取了非首个；枚举外被 `code` 清空 |
| `service_scope` | 原文明确列举服务项，输出为原文拼接（多项用 ` / `），无增删 | 服务项从上下文中整合但均为原文子串；仅做了分隔符规范化（顿号、`/`→` / `） | `value=""`；臆造原文未出现的服务；把贸易条款/运输方式误填入；多项合并后丢失关键项 |

#### 成对字段联动（起运/目的地）

| 场景 | 有值侧建议置信 | 空侧置信 |
| --- | --- | --- |
| 合写 `VNP/北京南` 或 `Beijing South/北京南` | en：高（代码/英文）；zh：高 | — |
| 仅中文（如「汽运至上海」） | zh：高或中 | en：`置信低`（禁止译成 Shanghai） |
| 铁路仅中文站名（如「成都南站」） | zh：高或中 | en：`置信低` |
| 仅 IATA/UN/LOCODE、无中文 | en 侧：高或中 | zh 侧：`置信低` |
| 路线「A → B」两侧均正确拆分 | 各侧：高或中 | — |
| 空运 + 港口码 / 海运 + IATA 等方式与码制不一致 | 值可保留原文标识；confidence **`置信中` 或 `置信低`**（instruction 取较低档） | — |
| 起运/目的角色标反 | 涉及字段：`置信低` | — |

#### `code` 节点强制降级（全局 + 按字段）

在模型产出置信度之后，`build_json` **逐字段**执行：

| 顺序 | 规则 | 影响字段 |
| --- | --- | --- |
| 1 | `value == ""` → `confidence = "置信低"` | 全部 11 字段 |
| 2 | `confidence` 不在 `{置信高, 置信中, 置信低}` → `"置信低"` | 全部 |
| 3 | `transport_mode` 不在七档白名单 → `value=""`，`confidence="置信低"` | `transport_mode` |
| 4 | `trade_terms` 不在十二档白名单 → `value=""`，`confidence="置信低"` | `trade_terms` |
| 5 | `urgency_level` 不在 `{普通, 加急}` → `value=""`，`confidence="置信低"` | `urgency_level` |
| 6 | `origin_port_zh` / `dest_port_zh` 去掉交通设施后缀（`港`、`机场`、`国际机场`、`站`、`火车站`、`高铁站`）；去后为空 → `value=""`，`confidence="置信低"` | 中文地点字段 |
| 7 | `service_scope` 非空但不含 ` / ` 且原文显然有多项（模型标高时）→ **不强制降级**，保留模型判断；仅做 strip | `service_scope` |
| 8 | 模型标 `置信高` 但字段属于同义归一路径（见上表「置信中」列）→ **不升级**；可保持模型原判，试跑阶段记录偏差 | 按字段 |

说明：`code` **不**根据原文重新计算置信度（无原文入参），只做**结构性兜底**（空值、非法枚举、非法置信档、中文「港」后缀）。语义级「高/中」判断由参数提取器在 instruction 中按上表完成。

#### 提取器 `instruction` 置信度输出要求

- 每个业务字段必须**同时**输出 `{field}` 与 `{field}_confidence`，共 22 个参数。
- 判定顺序：**先定 value → 再按上表「逐字段置信度规则」定 confidence**；不得所有非空字段一律标 `置信高`。
- 封闭枚举三字段：若走同义归一，confidence **不得**为 `置信高`（除非原文完整出现枚举值）。
- 未提及字段：`value=""` 且 `confidence="置信低"`（`urgency_level` 不得默认 `普通`）。


## 终点严格 JSON 形状（`result_json`）

`build_json` 输出字符串变量 `result_json`，**每个业务键**为对象 `{ "value": string, "confidence": string }`：

```json
{
  "customer_name": { "value": "", "confidence": "置信低" },
  "transport_mode": { "value": "", "confidence": "置信低" },
  "urgency_level": { "value": "", "confidence": "置信低" },
  "origin_port_en": { "value": "", "confidence": "置信低" },
  "origin_port_zh": { "value": "", "confidence": "置信低" },
  "dest_port_en": { "value": "", "confidence": "置信低" },
  "dest_port_zh": { "value": "", "confidence": "置信低" },
  "cargo_name": { "value": "", "confidence": "置信低" },
  "cargo_spec": { "value": "", "confidence": "置信低" },
  "trade_terms": { "value": "", "confidence": "置信低" },
  "service_scope": { "value": "", "confidence": "置信低" }
}
```

规则：

- 必须包含上述全部 **11** 个键，禁止增删键名。
- 禁止 `null`、禁止省略 `value` / `confidence`。
- `__is_success=0` 或上游全空时，仍输出上表空壳（各 `value=""`，`confidence="置信低"`）。
- `end` **只需**输出 `result_json`。

---

## 置信度设计决策

### 方案对比

| 方案 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| **A. 单 pass 参数提取器（推荐）** | 在现有 `extract_fields` 为每个字段增加 `{name}_confidence` 参数（共 22 个 string 参数） | 模型读原文时同步判断依据，置信与值一致；不增节点、不翻倍延迟 | 参数增多，instruction 变长；需试跑调优 |
| B. 第二个 LLM 节点 | `extract_fields` → `score_confidence`（llm）→ `build_json` | 职责分离 | **双倍 token/延迟/成本**；第二 pass 若只看抽取结果不看原文会失真；需额外节点与 prompt 维护 |
| C. 纯 code 规则算置信度 | 仅根据「是否原文子串匹配」「是否枚举归一」打分 | 零额外模型成本、可测 | 无法覆盖语义推断（如从上下文推公司名）；与「识别置信度」产品语义偏弱 |
| D. A + C 混合（**最终采用**） | 单 pass 由模型产出置信；`code` 做枚举校验与强制降级 | 兼顾语义判断与确定性兜底 | 实现略复杂于 v1 |

### 结论：**不新增 LLM 节点**

理由：

1. **置信度是抽取的元数据**，应在模型阅读同一篇原文、做同一轮判断时产出；拆成两次调用易出现「值来自第一遍、置信来自第二遍」不一致。
2. 参数提取器已支持多 `string` 参数；22 个参数在 Dify 1.16 参数提取器能力范围内，配合 `function_call`（目标工作区支持时）或 `prompt` 模式均可。
3. `code` 节点对三档封闭枚举做硬校验，可纠正模型越界输出，无需再调一次 LLM。
4. 若试跑发现置信度整体偏差大，优先 **加长 instruction 与 few-shot 示例**，仍不够再评估「LLM 结构化输出单节点替代 parameter-extractor」（仍保持单 pass，而非串联第二个 LLM）。

---

## 图计划

| 节点 ID | `data.type` | 输入 | 输出 |
| --- | --- | --- | --- |
| `start` | `start` | `inquiry_text`（paragraph，必填） | `inquiry_text` |
| `extract_fields` | `parameter-extractor` | `query: [start, inquiry_text]` | 11 业务字段 + 11 `{field}_confidence` + `__is_success` / `__reason` |
| `build_json` | `code` | 22 个字符串入参 | `result_json`（string） |
| `end` | `end` | `[build_json, result_json]` | `result_json` |

边：`start → extract_fields → build_json → end`（不变）。

### `extract_fields` 参数列表（22 + 系统）

业务值：`customer_name`、`transport_mode`、`urgency_level`、`origin_port_en`、`origin_port_zh`、`dest_port_en`、`dest_port_zh`、`cargo_name`、`cargo_spec`、`trade_terms`、`service_scope`

置信度：`customer_name_confidence`、`transport_mode_confidence`、`urgency_level_confidence`、`origin_port_en_confidence`、`origin_port_zh_confidence`、`dest_port_en_confidence`、`dest_port_zh_confidence`、`cargo_name_confidence`、`cargo_spec_confidence`、`trade_terms_confidence`、`service_scope_confidence`

### `extract_fields.instruction` 要点（v2）

- 输入是客户询价原文；只抽取、禁止臆造。
- 同步为**每个字段**输出置信度，仅允许 `置信高`/`置信中`/`置信低`。
- `transport_mode` / `trade_terms` / `urgency_level` 严格遵守封闭枚举；海运未标明 FCL/LCL 时 `transport_mode` 留空而非猜测。
- 起运/目的地四字段：`_*_en` **英文/代码优先**（见上节）；铁路含电报码、UIC、英文站名；与运输方式联动但不跨码制补全。
- 其余字段规则延续 v1（先出现、`service_scope` 用 ` / ` 等）。
- 字符串未出现 → `value=""`，对应 `confidence` 建议 `置信低`。

### `build_json`（Python `main`）要点（v2）

- 入参 22 个字符串（11 值 + 11 `_confidence`）。
- 定义常量集合：

```python
ALLOWED_TRANSPORT = {
    "海运 FCL", "海运 LCL", "空运", "铁路", "公路", "快递", "多式联运"
}
ALLOWED_TRADE_TERMS = {
    "EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"
}
ALLOWED_URGENCY = {"普通", "加急"}
ALLOWED_CONFIDENCE = {"置信高", "置信中", "置信低"}
ENUM_FIELDS = {
    "transport_mode": ALLOWED_TRANSPORT,
    "trade_terms": ALLOWED_TRADE_TERMS,
    "urgency_level": ALLOWED_URGENCY,
}
FIELD_ORDER = [
    "customer_name", "transport_mode", "urgency_level",
    "origin_port_en", "origin_port_zh", "dest_port_en", "dest_port_zh",
    "cargo_name", "cargo_spec", "trade_terms", "service_scope",
]
```

- 处理逻辑（每个字段统一走 `pack_field(name, value, confidence)`）：

```text
1. value = strip；None / "null" / "none" → ""
2. confidence = strip；不在 ALLOWED_CONFIDENCE → "置信低"
3. 若 name 在 ENUM_FIELDS：
     value 不在白名单 → value=""，confidence="置信低"
4. 若 value == "" → confidence="置信低"（覆盖模型输出）
5. 返回 {"value": value, "confidence": confidence}
```

- `json.dumps(..., ensure_ascii=False)` 按 `FIELD_ORDER` 固定 11 键顺序输出。
- 上游 `__is_success=0` 或全空时仍输出完整空壳 JSON。

---

## 文件结构

| 路径 | 职责 |
| --- | --- |
| `docs/plans/2026-08-25-inquiry-quote-extract.md` | 本计划 |
| `CONTEXT.md` | 领域 glossary（**v2 Task 0 同步**） |
| `docs/adr/0001-*.md` | 先出现策略（贸易条款仍适用） |
| `docs/adr/0003-*.md` | 紧急程度空值（**v2 修订**：枚举改为 `普通`/`加急`） |
| `docs/adr/0004-field-confidence-single-pass.md` | **新增**：置信度单 pass 决策记录 |
| `dsl/workflows/inquiry_quote_extract.yml` | Workflow DSL |

---

## 实施 Tasks

### Task 0: 同步领域文档与 ADR（v2 前置）

**Files:**

- Modify: `CONTEXT.md`
- Create: `docs/adr/0004-field-confidence-single-pass.md`
- Modify: `docs/adr/0003-empty-urgency-when-unspecified.md`（`紧急`→`加急` 表述）

- [ ] **Step 1:** 更新 glossary：`物流类型`→`运输方式`及 7 档枚举；`报价条款`→`贸易条款`；紧急程度枚举；`抽取结果 JSON` 双层结构说明。
- [ ] **Step 2:** 新增 ADR-0004 记录「单 pass 参数提取器 + code 降级」决策及否决第二 LLM 的理由。
- [ ] **Step 3:** 修订 ADR-0003 中 `紧急`/`普通` 为 `加急`/`普通`。

---

### Task 1: 用 MCP 核对参数提取器多参数与 code 装配

**Files:**

- 只读：`dify-docs` MCP、`references/node-schemas.md`

- [ ] **Step 1:** 查参数提取器参数数量上限、22 个 `string` 参数可行性、`function_call` vs `prompt`。
- [ ] **Step 2:** 确认 `code` 节点 22 入参引用写法。
- [ ] **Step 3:** 记录模型占位符策略。

---

### Task 2: 更新 Workflow DSL YAML（v2）

**Files:**

- Modify: `dsl/workflows/inquiry_quote_extract.yml`

- [ ] **Step 1:** 重命名并更新 `extract_fields.parameters`（11 值 + 11 置信度）；更新 instruction 含枚举与置信口径。
- [ ] **Step 2:** 重写 `build_json`：枚举白名单、置信降级、双层 JSON 装配。
- [ ] **Step 3:** 更新 `build_json.variables` 共 22 条 `value_selector`。
- [ ] **Step 4:** 自检：无密钥；`version: "0.7.0"` 有引号；`end` 仅 `result_json`。

---

### Task 3: 严格校验并试跑样例（v2）

- [ ] **Step 1:** `python scripts/validate_dsl.py --strict --target-version 0.7.0 dsl/workflows/inquiry_quote_extract.yml`
- [ ] **Step 2:** 按失败诊断修 YAML直至 exit 0。
- [ ] **Step 3:** 交付说明（导入、重连凭据、Breaking change 提示）。

**试跑样例 A（海运 FCL + CIF + 普通）：**

```text
客户：宁波海天贸易有限公司
走海运 FCL，普通时效。起运 CNNGB/宁波，目的 USLAX/洛杉矶。
货名：塑料配件。规格约1,200KG，6CBM。
服务：订舱 / 起运港 THC / 目的港 THC。
条款 CIF。
```

**期望 `result_json`（完整）：**

```json
{
  "customer_name": { "value": "宁波海天贸易有限公司", "confidence": "置信高" },
  "transport_mode": { "value": "海运 FCL", "confidence": "置信高" },
  "urgency_level": { "value": "普通", "confidence": "置信中" },
  "origin_port_en": { "value": "CNNGB", "confidence": "置信高" },
  "origin_port_zh": { "value": "宁波", "confidence": "置信高" },
  "dest_port_en": { "value": "USLAX", "confidence": "置信高" },
  "dest_port_zh": { "value": "洛杉矶", "confidence": "置信高" },
  "cargo_name": { "value": "塑料配件", "confidence": "置信高" },
  "cargo_spec": { "value": "约1,200KG，6CBM", "confidence": "置信高" },
  "trade_terms": { "value": "CIF", "confidence": "置信高" },
  "service_scope": { "value": "订舱 / 起运港 THC / 目的港 THC", "confidence": "置信高" }
}
```

（样例含「普通时效」故 `urgency_level` 为 `普通`/`置信中`；删去时效措辞则应为 `""`/`置信低`。）

**试跑样例 B（公路 + 加急）：**

```text
客户：苏州恒达机电有限公司
公路运输，加急。货名：电机配件，约 800KG，送至上海。
```

**期望：**

- `transport_mode.value` = `"公路"`（`汽运` 同义归一）
- `transport_mode.confidence` = `"置信中"`（同义归一）
- `urgency_level.value` = `"加急"`
- `dest_port_zh.value` = `"上海"`

**试跑样例 C（海运未区分 FCL/LCL）：**

```text
客户：测试公司
走海运，宁波到洛杉矶。
```

**期望：**

- `transport_mode.value` = `""`（禁止猜 FCL/LCL）
- `transport_mode.confidence` = `"置信低"`

**试跑样例 D（空运 + IATA）：**

```text
客户：深圳电子有限公司
空运加急。起运 CAN/广州，目的 LAX/洛杉矶。
货名：电路板，约 200KG。
条款 FOB。
```

**期望：**

- `transport_mode` = `{ "value": "空运", "confidence": "置信高" }`
- `origin_port_en` = `{ "value": "CAN", "confidence": "置信高" }`
- `origin_port_zh` = `{ "value": "广州", "confidence": "置信高" }`
- `dest_port_en` = `{ "value": "LAX", "confidence": "置信高" }`
- `dest_port_zh` = `{ "value": "洛杉矶", "confidence": "置信高" }`

**试跑样例 E（铁路 + 仅中文站名）：**

```text
客户：成都机械设备公司
铁路运输。成都南站 → 西安北站。货名：阀门，约 15CBM。
```

**期望：**

- `transport_mode` = `{ "value": "铁路", "confidence": "置信高" }`
- `origin_port_zh` = `{ "value": "成都南", "confidence": "置信高" }`
- `dest_port_zh` = `{ "value": "西安北", "confidence": "置信高" }`
- `origin_port_en` / `dest_port_en` = `""` / `置信低`（原文无拉丁标识，**禁止**译成 `Chengdu South`）

**试跑样例 E2（铁路 + 电报码/英文，英文优先）：**

```text
客户：中欧班列运营部
Rail freight. Origin VNP/北京南 to EAY/西安北. Cargo: auto parts.
```

**期望：**

- `transport_mode` = `{ "value": "铁路", "confidence": "置信高" }`
- `origin_port_en` = `{ "value": "VNP", "confidence": "置信高" }`（合写优先电报码；若原文为 `Beijing South/北京南` 则 en=`Beijing South`）
- `origin_port_zh` = `{ "value": "北京南", "confidence": "置信高" }`
- `dest_port_en` = `{ "value": "EAY", "confidence": "置信高" }`
- `dest_port_zh` = `{ "value": "西安北", "confidence": "置信高" }`

**试跑样例 F（多式联运 + 异构代码）：**

```text
客户：义乌小商品贸易公司
多式联运。起运 CNNGB/宁波，目的 FRA/法兰克福。
```

**期望：**

- `transport_mode` = `{ "value": "多式联运", "confidence": "置信高" }`
- `origin_port_en` = `CNNGB`，`origin_port_zh` = `宁波`（海运段港口码）
- `dest_port_en` = `FRA`，`dest_port_zh` = `法兰克福`（空运段机场码；与运输方式「多式联运」一致，置信高或中）

---

## 明确不做（YAGNI）

- 不做 Chatflow / 多轮澄清
- 不做 Agent v2 / 知识库 / HTTP 回写
- **不做第二个 LLM 节点专责置信度**（除非 v2 试跑后单 pass 置信度验收不达标，再开 ADR 复审）
- 不做地点代码补全表（港口 / 机场 / 铁路等码制互转）
- 不恢复 `is_urgent`、金额/币种
- 不在未要求时提交 git commit

---

## Spec 覆盖自检（v2）

| 需求 | 对应 |
| --- | --- |
| 运输方式 7 档封闭枚举 | `transport_mode` + instruction + `build_json` 白名单 |
| 贸易条款 12 档封闭枚举 | `trade_terms` + instruction + `build_json` 白名单 |
| 紧急程度 `普通`/`加急` | `urgency_level` + ADR-0003 修订 |
| 每字段置信度三档 | 11×`{value,confidence}` + **逐字段判定表** + instruction |
| 单 pass、不增 LLM | ADR-0004 + 图计划 |
| 封闭枚举 code 兜底 | `transport_mode` / `trade_terms` / `urgency_level` 白名单 |
| 多运输方式地点统一识别 | 「起运/目的地与地点代码」+ 样例 D/E/E2/F |
| `_*_en` 英文/代码优先 | 英文优先原则 + 铁路电报码/UIC/英文站名 |
| 地点码制不做白名单校验 | `build_json` 仅 strip / 中文后缀 |
| Breaking API 变更 | v2 变更摘要 |
| v1 已完成部分 | Task 1–3（v1）已勾选；**v2 Task 0–3 待实施** |

---

## v1 实施记录（已完成，供对照）

v1 已交付 `dsl/workflows/inquiry_quote_extract.yml`（平铺 11 键、`logistics_type`/`quote_terms`/无置信度）。v2 在此基础上改版，不另建新文件。
