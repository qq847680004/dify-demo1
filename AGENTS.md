# Agent Guidelines

## Rules Index

All development tasks must follow the rules in `.cursor/rules/`:

| Rule | Target File | Trigger / Scope | Core Constraints |
| --- | --- | --- | --- |
| **Pipeline** | [dify-agent-pipeline.mdc](file:///d:/2026work/work/dify-demo1/.cursor/rules/dify-agent-pipeline.mdc) | 生产/修改 Dify DSL | `dify-docs` MCP 查文档 → `$dify-workflow-dsl` 写 DSL → `scripts/validate_dsl.py` 严格校验 |
| **DSL 0.7** | [dify-dsl-0.7.mdc](file:///d:/2026work/work/dify-demo1/.cursor/rules/dify-dsl-0.7.mdc) | 编排 DSL 图结构、节点与变量 | 顶层 `version: "0.7.0"`；节点 ID 仅字母/数字/下划线；变量引用 `{{#node_id.field#}}`；LLM 节点须带 `context` |
| **Agent v2** | [dify-agent-v2.mdc](file:///d:/2026work/work/dify-demo1/.cursor/rules/dify-agent-v2.mdc) | 独立 Agent App 或 Agent 节点 | 能力（soul）与任务分离；`agent_packages` 映射；`inline_agent` 结构 |
| **Model Tier** | [dify-llm-model-tier.mdc](file:///d:/2026work/work/dify-demo1/.cursor/rules/dify-llm-model-tier.mdc) | 节点模型选型 | 默认 `qwen3.7-flash`（短文抽取、分类、枚举）；复杂规则算费/多源合成才用 `qwen3.7-plus`；识图用 `qwen3-vl-flash` |
| **Safety** | [dify-production-safety.mdc](file:///d:/2026work/work/dify-demo1/.cursor/rules/dify-production-safety.mdc) | 外部接口、凭据与插件 | 严禁硬编码密钥与敏感 ID；插件 `dependencies` 原样保留；导入后必须重连凭据 |

## Agent Skills

### Issue Tracker
Issues/specs 位于 `.scratch/<feature-slug>/` 目录。详见 `docs/agents/issue-tracker.md`。

### Triage Labels
标准标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain Docs
领域映射入口：`CONTEXT-MAP.md` $\rightarrow$ 各子域 `CONTEXT.md`；架构决策记录位于 `docs/adr/`。详见 `docs/agents/domain.md`。
