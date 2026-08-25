# 缺省报价金额用 0 而非 null

对外 JSON 禁止 null 且键必须齐全。未抽到报价时 `quote_amount` 为 `0` 且 `quote_currency` 为空字符串，用这对组合表示「无报价」，避免引入额外布尔字段或打破严格 JSON 契约。
