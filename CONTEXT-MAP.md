# Context Map

## Contexts

- [询价字段抽取](./CONTEXT.md) — 从非结构化询价文本抽出固定业务字段
- [BtoB 电商客服](./docs/b2b-ecommerce/CONTEXT.md) — 按企业知识库回答采购方企业的咨询

## Relationships

- 两个 context 彼此独立，不共享术语。询价里的「客户名称」不是客服里的「客户」。
- 不通过事件或同步调用互操作；各自对应一份 Dify App DSL。
