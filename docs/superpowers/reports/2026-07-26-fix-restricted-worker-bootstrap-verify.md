# Restricted worker bootstrap 加固验证报告

## 结论

PASS。`RestrictedBackend` 现在以 Python isolated mode 启动已安装的
`forgeagent._sandbox_worker`，任务目录、用户 site-packages 和 `PYTHONPATH` 无法在
audit hook 安装前替换 worker 或 runtime。3/3 tasks、1/1 requirement、2/2 scenarios
均有实现与测试证据，未发现 CRITICAL、WARNING 或 SUGGESTION 项。

## 规格核验

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| Completeness | PASS | 3/3 tasks 完成；1/1 requirement 已实现 |
| Correctness | PASS | worker shadow 与 installed worker 两个场景均有真实子进程覆盖 |
| Coherence | PASS | 实现遵循 design 中的原生 `-I` 决策，未引入 launcher、依赖、配置或公共 API |

映射关系：

- `src/forgeagent/executor.py` 在 restricted worker 命令中加入 `-I`，直接落实
  installation-bound bootstrap requirement。
- `tests/test_restricted_backend.py` 在真实任务目录创建伪造
  `forgeagent/_sandbox_worker.py` 与 `runtime.py`，同时设置恶意 `PYTHONPATH`，断言两个
  shadow marker 均未出现且真实 worker 正常返回。
- `docs/threat-model.md` 明确 isolated bootstrap 的保护范围，并保留 restricted 不是
  OS 级 sandbox 的剩余风险。

## TDD 证据

回归测试先在未加固命令上运行并进入 RED：真实子进程返回 `shadow worker`，证明任务
目录中的伪造 worker 可以抢先执行。生产命令加入 `-I` 后，同一测试进入 GREEN，输出
为 `installed worker`，worker/runtime 两个标记文件均不存在。

## 最终门禁

| 检查 | 结果 |
| --- | --- |
| 安全专项 | `55 passed in 16.39s` |
| 完整 pytest | `2251 passed, 10 skipped in 140.47s` |
| 离线 golden | `20/20 passed (100.0%)` |
| Ruff check | `All checks passed!` |
| Ruff format | `105 files already formatted` |
| wheel/sdist | 成功生成 `forgeagent-0.1.0-py3-none-any.whl` 与 `forgeagent-0.1.0.tar.gz` |
| OpenSpec strict | `19 passed, 0 failed` |
| Git diff check | PASS，无空白错误 |

完整 pytest 首次在命令沙箱内运行时得到 `12 failed, 2227 passed, 22 skipped`：11 项
失败来自沙箱禁止 loopback 端口，1 项来自嵌套 `uv build` 受限。随后在真实项目测试
环境以相同命令复跑，得到上述 `2251 passed, 10 skipped`；剩余 skip 均为 Docker
daemon/image 不可用的既有环境项。

Comet 的 build guard 当前只自动推断 JavaScript、Maven 与 Cargo 构建，无法识别本项目
的 Python/uv 构建。已先独立运行 `uv build` 并确认 wheel/sdist 成功，再使用
`COMET_SKIP_BUILD=1` 跳过 guard 中不适用的重复推断；该变量没有跳过任何项目构建或
测试证据。

## 审查与剩余风险

hotfix 状态配置为 `review_mode: off`，因此按 Comet 规则未派发自动代码审查；full
verify 已直接检查正确性、安全边界、scenario 覆盖和设计一致性。

剩余风险不因本次变更扩大：restricted 仍是应用层隔离，无法防御受损的解释器安装、
原生扩展或内核级绕过；高风险不可信代码继续使用 container backend。Docker 平台测试
未在本机取得运行证据，但本次未修改 container 路径。
