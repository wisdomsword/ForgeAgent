## 1. 身份契约回归

- [x] 1.1 增加专项测试，要求 Agent 风格显式 role 中的 ForgeAgent-first 身份组合并拒绝 native-first 措辞。
- [x] 1.2 增加 Task 终态测试，覆盖身份问句的错误前缀纠正、正确前缀保留和普通问句不改写。

## 2. 提示修正

- [x] 2.1 更新 fixed system、default SOUL、protocol 和发布 smoke 标记，强制 ForgeAgent 产品身份优先且不引导 native persona。

## 3. 验证

- [x] 3.1 运行专项 identity/task 测试及项目要求的验证套件。
- [x] 3.2 使用真实模型回放身份问题并确认回答以 ForgeAgent 开头。
