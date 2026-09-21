# Context Map

## Contexts

- [询价字段抽取](./CONTEXT.md) — 从非结构化询价文本或图片抽出固定业务字段（DSL：`inquiry_intent_classify.yml`、`inquiry_quote_extract.yml`、`inquiry_quote_extract_image.yml`）
- [报价推荐](./docs/quote-recommend/CONTEXT.md) — 根据询价单基础字段生成报价草案（DSL：`inquiry_quote_recommend.yml`）
- [BtoB 电商客服](./docs/b2b-ecommerce/CONTEXT.md) — 按企业知识库回答采购方企业的咨询
- [可溯源 AI 智助箱](./docs/traceable-ai-assistant/CONTEXT.md) — 按运价/港口/货关/案例库为内部业务员作答

## Relationships

- 四个 context 彼此独立，不共享术语。询价抽取里的「客户名称」不是客服里的「客户」，也不是智助箱里的「业务员」。
- 报价推荐不直接调用抽取 App。抽取 `result_json.supplement` 是一段文字，后端落库后可回放到推荐流 `start.supplement`（也可由业务员另填）。用语与询价工作台的报价草案 / 召回线索 / 补充信息、AI 数据的有效运价 / 相似历史单 / 费用项对齐，不另造同义词。
- 不通过事件或同步调用互操作；各自对应一份 Dify App DSL。
