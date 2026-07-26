## Fix

将状态读取拆成明确顺序：先执行有界二进制读取；若字节数超限，立即抛出稳定 `ValueError("collaboration state is too large")`；只有未超限数据才进入 decode/JSON parse，并将该阶段所有可预期异常统一转换为 `invalid collaboration state JSON`。这样错误类别由控制流决定，不依赖异常文案。

唯一性测试使用两个完整、合法且相同的 ID，并精确断言 `plan item ids must be unique`，同时保证不出现 ID 格式错误，证明唯一性分支实际执行。
