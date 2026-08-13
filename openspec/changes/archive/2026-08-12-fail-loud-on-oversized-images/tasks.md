# 任务：超限图片输入显式失败

- [x] 反向修改目录超限图片的错误回归，并补充大型非图片不全量读取的 RED 用例。
- [x] 让单文件和目录复用先 `stat`、有界头部识别和完整读取的加载逻辑。
- [x] 运行 `tests/test_multimodal.py` 聚焦测试、Ruff 与 OpenSpec strict 验证。
