# Context Map

## Contexts

- [询价字段抽取](./CONTEXT.md) — 从非结构化询价文本抽出固定业务字段
- [BtoB 电商客服](./docs/b2b-ecommerce/CONTEXT.md) — 按企业知识库回答采购方企业的咨询
- [可溯源 AI 智助箱](./docs/traceable-ai-assistant/CONTEXT.md) — 按运价/港口/货关/案例库为内部业务员作答

## Relationships

- 三个 context 彼此独立，不共享术语。询价里的「客户名称」不是客服里的「客户」，也不是智助箱里的「业务员」。
- 不通过事件或同步调用互操作；各自对应一份 Dify App DSL。
