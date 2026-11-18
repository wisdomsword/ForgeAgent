# Proposal

## Why

发布前评审复现了宿主回执可被任务代码删除、主进程文件读取和执行输出无界、相对路径不一致、解析与显示崩溃、客户端重试及发现错误；默认验证还有六个失败，GitHub 缺少对应 CI。用户已要求全部修复。

## What Changes

- 保护回执权威状态，保留旧记录并对缺失或不可信状态 fail closed。
- 在读取和捕获入口限制文件、Skill、图片数量、worker 输出和状态大小；拒绝特殊文件。
- 修复 restricted 工作目录、非法协议/HTTP 字段、SDK 双重重试、模型发现缓存/超时及 Rich 外部文本渲染。
- 修复离线测试的历史哈希依赖和文档基线，统一 OpenSpec 工具版本，增加 GitHub 离线及 Linux Docker 门禁。
- 忽略本地凭据和运行状态，改善首页安装入口并增加安全报告说明。
- 不推送、不发布、不创建正式 tag，不读取真实模型凭据或调用收费模型。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `external-action-receipts`: 宿主权威状态不受任务代码写入，丢失已登记回执拒绝继续。
- `tool-approval`: 文件读取和执行输出在入口有界，任务工作目录稳定，外部显示文本按字面处理。
- `tool-call-identity`: 无效工具名类型成为结构化解析错误。
- `http-task-service`: 非法字段类型产生 400。
- `model-client-lifecycle`: SDK 不重复重试，发现请求和缓存受限且正常关闭。
- `skills-runtime`: Skill 读取本身有界。
- `image-input`: 图片数量超限时及时停止加载。
- `continuous-verification`: GitHub 门禁、可移植测试、统一工具链和真实基线。

## Impact

修改上述运行时模块与对应测试、发布 CI、忽略规则、README 和安全文档。复用标准库与现有依赖；保留纯文本协议、模型路由、人工确认和既有沙箱档位。回执保护是安全修复，旧项目回执不得静默丢弃或自动重放。
