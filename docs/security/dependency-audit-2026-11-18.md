# 依赖漏洞与许可证审计（2026-11-18）

**结论：当前依赖安全验收不通过，建议修复后再制作发布版本。** 当前源码仍可按 MIT
公开；这不意味着安装时取得的所有第三方依赖都属于 MIT，也不表示已发现默认配置下的
完整远程攻击链。本轮是审计，没有升级依赖或更改运行时行为。

## 范围与证据

审计基线：`0c46ea4736b21e260653052fa7a538f2c1a55ef5`。
`uv.lock` SHA256：`b1e1ebd2f12e355110707953c3e9b87d31ae7ec37b1cabe6cc72d51490b4ce76`。
完整清单及许可证文件摘要见 [机器可读清单](dependency-inventory-2026-11-18.json)。

| 范围 | 实际检查 | 结果 |
|---|---|---|
| uv.lock 的外部 Python 包 | 52 包，包含所有平台条件依赖；47 个运行时包、5 个仅开发包 | 5 包命中 24 组通告 |
| Python 漏洞源 | pip-audit 2.10.1，PyPI 与 OSV 两源 | PyPI 原始 26 条、OSV 原始 43 条；按 ID/aliases 合并后均为 24 组，无跳过包 |
| Python 许可证 | 50 个本机安装分发包的许可证文件；另下载 colorama 与 pywin32 的锁定 Windows wheel 并校验 SHA256 | 52 包均取得许可证文件；发现 MPL 和 pywin32 内附 LGPL 文本 |
| 构建依赖 | 对未锁定的 hatchling 做本日独立解析，共 6 包 | PyPI 漏洞扫描 0 命中；仅是本日解析结果 |
| CI 的 uv 0.11.1 | pip-audit 与上游通告核对 | 3 组通告；本机 uv 0.12.13 也低于 CA 修复版本 |
| CI 的 OpenSpec 1.13.1 | 隔离生成当前 npm 依赖树，90 个 package 条目；禁用安装脚本 | npm audit 标出 4 个受影响包，根因是同一项 picomatch 通告 |
| npm 许可证 | 当前 90 个 package 条目的 lock 元数据 | MIT、ISC、BSD-3-Clause，无缺失项；未逐包核验 tarball 许可证 |
| 已安装包兼容性 | uv pip check | `All installed packages are compatible`，不等于无漏洞 |

应用锁文件与工具链合计 28 组通告，上游评级为 Critical 4、High 9、Moderate 14、Low 1。
评级来自上游，并非项目实际可利用性的评级；通告之间也可能描述重叠问题。

原始扫描 JSON、完整上游记录、许可证文件和本地复现结果保存于忽略目录
`artifacts/dependency-audit-2026-11-18/`。审计通过公开包名与版本查询漏洞库，没有提交
模型凭据或用户数据。审计器通过隔离工具环境运行，未加入项目依赖。

## 漏洞发现与修复方案

### P1：锁定运行时依赖需要升级

| 包 | 当前版本 | 去重通告数 | 上游最高评级 | 建议最低候选版本 |
|---|---|---:|---|---|
| anyio | 4.14.1 | 3 | Critical | 4.14.2 |
| certifi | 2026.6.17 | 1 | Critical | 2026.10.18 |
| cryptography | 49.0.0 | 1 | High | 50.0.0 |
| mcp | 1.28.1 | 4 | Moderate | 1.30.0，保持现有 `<2` 主版本约束 |
| pyjwt | 2.13.0 | 15 | Critical | 2.15.0 |

五个候选版本均已在 PyPI 发布，Python 最低版本要求兼容项目的 Python ≥3.11 声明，
其版本元数据中的漏洞列表均为空。这是候选版本的数据库检查，**尚未验证五项联合升级
后的依赖解析、回归、Docker 或真实模型行为**。

具体暴露面：

- **MCP outputSchema 外部引用可达**：
  [GHSA-rwrf-2pqf-9j8j](https://osv.dev/vulnerability/GHSA-rwrf-2pqf-9j8j)。
  项目 `MCPManager._holder` 创建 stdio `ClientSession`，`_call_tool_on_loop` 调用
  `session.call_tool`，SDK 随后使用 jsonschema 默认解析器校验服务端 `outputSchema`。
  本轮在 1.28.1 的该校验方法上使用纯 loopback 模拟服务，观察到一次 `/schema` GET。
  未访问外部服务，也未执行攻击代码。该问题不限于 HTTP MCP transport；启用 MCP 并调用
  带外部引用输出 schema 的工具即可进入此路径。默认 MCP 配置为空；配置的 MCP 子进程
  本身属于用户选择的可信执行程序。本轮确认了 SDK 读取行为，没有复现无期限阻塞。
- **MCP 另外三项通告**涉及 StreamableHTTP 服务端会话回收、HTTP 客户端重定向和服务端
  bearer audience 验证。当前集成只创建 stdio 客户端，未发现它们在现有产品集成中的直接
  触发路径；仍应随 SDK 升级一并消除，不能将版本命中直接称为已确认可利用。
- **certifi 信任库问题**：
  [GHSA-6q48-6c7w-9gw2](https://osv.dev/vulnerability/GHSA-6q48-6c7w-9gw2)。
  包中仍信任涉及中间 CA 私钥泄露事件的 emSign 根。该包经 httpcore/httpx 进入真实模型
  网络调用依赖链，应优先更新；本轮没有实施中间人攻击或验证攻击成立。
- **AnyIO**包括 IDNA 主机名/TLS 校验、`extra_groups` 进程权限和进程池 stderr 阻塞问题。
  它经 SDK、httpx 和 MCP 等路径进入依赖图，但未发现产品直接调用 AnyIO，上述具体
  触发场景没有在本轮复现。不能把它们统称为当前 Agent 已经发生 TLS 或权限绕过。
- **PyJWT 和 cryptography**经 `mcp → pyjwt[crypto] → cryptography` 安装。
  AST 检查未发现产品直接导入 jwt 或 cryptography；当前 stdio 集成未使用 SDK 的 JWT
  服务端认证或 PKCS#7 解密。它们是需要升级的运行时依赖，实际攻击面取决于使用方式。
  PyJWT 一项通告没有列出 `fixed`，但以 `last_affected: 2.13.0` 限定范围，不能据此断言
  “没有可用修复”；2.15.0 的版本检查未命中这些记录。

修复时应更新锁文件中的这五个包，并将直接依赖 `mcp` 的最低版本提高到 1.30.0。
仅更新 uv.lock 不会改变 wheel 的依赖下限。对于 `pip install` 分发，应提供经过审计的
约束清单或制定受支持版本策略；避免为了加下限而把所有传递依赖无条件提升为直接依赖。
随后运行完整离线回归、真实 MCP 边界测试、Golden、Linux Docker 和安装包冒烟。

### P1：CI 固定的 uv 也需要升级

| 通告 | 上游评级 | 影响 | 首个修复版本 |
|---|---|---|---|
| [GHSA-pjjw-68hj-v9mw](https://osv.dev/vulnerability/GHSA-pjjw-68hj-v9mw) | Low | wheel RECORD 路径导致任意文件删除 | 0.11.6 |
| [GHSA-4gg8-gxpx-9rph](https://osv.dev/vulnerability/GHSA-4gg8-gxpx-9rph) | Moderate | entry point 名称导致任意文件写入 | 0.11.15 |
| [GHSA-hq85-5cpj-mr62](https://osv.dev/vulnerability/GHSA-hq85-5cpj-mr62) | Critical | 内置信任库包含涉事 emSign 根 | 0.13.4 |

应同时检查 GitHub/GitLab CI 的 uv 固定版本和安装文档。0.13.4 已发布，PyPI 该版本
元数据漏洞列表为空。这里不升级本机工具；当前本机 0.12.13 仍处于第三项影响范围。
修复后需要重新验证锁文件兼容、构建和完整 CI。

### P2：OpenSpec 的 npm 通告不能用盲目升级处理

[GHSA-fc5q-39xc-vjpf](https://osv.dev/vulnerability/GHSA-fc5q-39xc-vjpf)
描述 picomatch 接受恶意重复 extglob 时的正则拒绝服务，上游评级 High。
当前重新解析的路径为：

```text
@fission-ai/openspec 1.13.1 → fast-glob 3.3.3 → micromatch 4.0.8 → picomatch 2.3.2
```

npm audit 的“四个 High”是一个根通告向四个包传播，并非四个独立漏洞。
该工具用于开发和 CI，不进入 ForgeAgent 的运行时依赖或 wheel。是否能由不可信输入
触发当前 `openspec validate --all --strict` 命令，尚未完成调用参数层面的验证。

本轮分别解析并审计 OpenSpec 1.14.3 和当前 2.1.0，两者仍各有四个受影响包条目，
通过 `tinyglobby/fdir` 等路径命中相同 picomatch 通告。因此不建议直接执行
`npm audit fix --force` 或把升级最新版当作问题已关闭。

处理方案：向上游确认已修复 picomatch 的发布/回移补丁；取得兼容修复后固定完整工具
依赖树并复扫。如果需要先接受开发工具的有限风险，应记录实际输入可达性和接受期限，
不得在扫描中静默忽略。当前没有已验证干净的 OpenSpec 替代树。

### P2：构建和外部工具的传递版本没有冻结

`[build-system].requires` 只有未固定版本的 `hatchling`。本日独立解析得到
hatchling 1.33.0、packaging 26.3、pathspec 1.1.1、pluggy 1.7.0、tomlkit 0.15.2、
trove-classifiers 2026.9.21.13，六个包的本次 PyPI 扫描无命中。这不是此前 CI 构建环境
的精确取证，也不能保证未来解析结果相同。

OpenSpec 虽固定 CLI 版本，全局 npm 安装的传递版本也没有项目锁定清单。
建议固定可复现的构建/工具约束，并在独立依赖安全门禁中定期或随变更复扫。
保持运行时依赖轻量，不把审计工具塞进产品依赖。

## 许可证与公开分发义务

### 当前 GitHub 源码与普通 wheel

ForgeAgent 采用 MIT。当前构建配置只打包本项目源码和资源，第三方 Python 包由包管理器
另行取得，没有发现把这些依赖的源码整体 vendoring 入 wheel 的配置。
声明依赖和记录锁文件，不等于将第三方代码统一重新许可为 MIT。

本轮没有发现必须仅因这些依赖就把 ForgeAgent 整体改为 GPL 的依据。第三方包仍有各自
的版权、许可证和分发条件；下面的条件对未来离线包、自包含安装器及镜像尤其重要。

### 需要保留的附加义务

| 包/组件 | 许可证发现 | 分发时的要求 |
|---|---|---|
| certifi 2026.6.17 | MPL-2.0，许可证文件明确包含 Mozilla CA bundle 的来源 | 保留许可证与来源，满足所分发 MPL 文件的对应源码获取义务；修改受覆盖文件时遵守 MPL |
| tqdm 4.68.4 | `MPL-2.0 AND MIT`，不是可任意二选一 | 保留两类声明，按文件和贡献记录履行相应义务 |
| pywin32 312 / adodbapi | wheel 内实际包含 GNU LGPL 2.1 完整文本；顶层 PyPI `PSF` 标签不足以描述整个 wheel | 分发整个 Windows wheel/自包含包时保留全部子组件许可证，核对对应源码获取及用户替换/调试库的权利；LGPL only/or-later 的具体适用尚未判定 |
| pywin32 其他组件 | BSD 风格条款、Scintilla 许可、MAPIStubLibrary 的 MIT 声明等 | 不能只附 PSF 标签；保留各子组件版权、免责声明和 NOTICE |
| Apache-2.0 依赖 | 如 openai、distro；cryptography/packaging 等提供双许可选择 | 适用 Apache 路径时保留许可证、版权及上游提供的 NOTICE；遵守修改标记要求 |
| pathspec 1.1.1 | 本日构建工具解析的 MPL-2.0 | 不进入当前运行时 wheel；若以后分发构建工具或其代码，同样履行 MPL 条件 |
| MIT / BSD / ISC / PSF 等 | 其余顶层声明见清单 | 保留各自所需版权、许可和免责声明，不以项目 MIT 替换它们 |

Windows wheel 的 SHA256 已与 uv.lock 核对，LGPL 文本分别位于
`adodbapi/license.txt` 与 `pywin32-312.dist-info/licenses/adodbapi/license.txt`。
该发现不表示整个 pywin32 或 ForgeAgent 都是 LGPL；它说明自包含 Windows 分发不能只看
顶层元数据。当前报告未穷举所有原生二进制内嵌依赖的来源，不能替代打包产物级合规审查。

## 最小整改顺序

1. 更新五个 Python 锁定包及 MCP 下限，升级 CI uv 至至少 0.13.4，复扫并运行现有门禁。
2. 为 MCP 外部 outputSchema 引用补确定性回归，验证修复后不发起额外网络或文件读取。
3. 处理或明确接受 OpenSpec 工具链的单项 picomatch 风险；不要用错误的 npm 修复提示关闭它。
4. 完善第三方分发说明；发布自包含 Windows/离线包前单独核对 LGPL、MPL 和 NOTICE。
5. 建立独立、固定工具版本的依赖安全检查，分别覆盖运行时、构建、开发工具与条件依赖。

## 复查方式与未验证项

扫描应从锁文件生成全平台无 marker 的精确包版本清单，使用
`pip-audit==2.10.1 --no-deps --disable-pip -r <清单> --vulnerability-service pypi`
并用 `--vulnerability-service osv` 交叉验证。精确列表只用于查询，不安装这些包；
源 wheel 的下载完整性以原始 uv.lock 哈希为准，不能把去掉哈希的扫描输入当作安装清单。
本轮扫描非零退出码原文：

```text
Found 26 known vulnerabilities in 5 packages
Found 43 known vulnerabilities in 5 packages
```

npm 使用 `--package-lock-only --ignore-scripts` 在隔离目录生成清单，再 `npm audit --json`。
原始 JSON 中保留受影响树、上游 URL 与 audit 退出结果。候选包“0 命中”只适用于查询当日、
指定数据源和精确版本，不表示不存在未知漏洞。

本轮未修改源代码、依赖声明、uv.lock、CI 或本机工具，也未运行升级后的测试。
Docker 基础镜像/OS、Python/Node 解释器安全版本、GitHub Actions 实现、用户自选 MCP
服务器及模型服务条款不在本次包审计的完整覆盖范围。不能将本报告外推为这些组件的安全结论。

## 通告明细

以下按 GHSA 列出合并后的通告；修复范围和别名见机器可读清单。

| 包 | 通告 | 上游评级 | 摘要 |
|---|---|---|---|
| pyjwt | [GHSA-2gx3-rcp4-g85q](https://osv.dev/vulnerability/GHSA-2gx3-rcp4-g85q) | MODERATE | PyJWT: PyJWKClient still amplifies unauthenticated JWKS fetches on unknown kid values (incomplete fix of CVE-2026-48524) |
| anyio | [GHSA-3w57-8xmc-8v26](https://osv.dev/vulnerability/GHSA-3w57-8xmc-8v26) | HIGH | AnyIO run_process/open_process ignores extra_groups and can retain parent supplementary groups |
| pyjwt | [GHSA-42vr-xj54-vc7v](https://osv.dev/vulnerability/GHSA-42vr-xj54-vc7v) | MODERATE | PyJWT: Unauthenticated RecursionError DoS in pre-verification payload parse (PyJWKClient.get_signing_key_from_jwt / verify_signature=False) |
| uv | [GHSA-4gg8-gxpx-9rph](https://osv.dev/vulnerability/GHSA-4gg8-gxpx-9rph) | MODERATE | uv is vulnerable to arbitrary file write through entry point names |
| mcp | [GHSA-5h93-6whr-6q8j](https://osv.dev/vulnerability/GHSA-5h93-6whr-6q8j) | MODERATE | Model Context Protocol Python SDK: HTTP client transports followed cross-origin redirects carrying custom headers and bodies |
| anyio | [GHSA-5p39-cfhj-2xmp](https://osv.dev/vulnerability/GHSA-5p39-cfhj-2xmp) | MODERATE | AnyIO process-pool workers can block indefinitely on undrained stderr |
| certifi | [GHSA-6q48-6c7w-9gw2](https://osv.dev/vulnerability/GHSA-6q48-6c7w-9gw2) | CRITICAL | certifi bundles emSign root CAs with compromised intermediate CA keys |
| anyio | [GHSA-82r6-8w77-94w6](https://osv.dev/vulnerability/GHSA-82r6-8w77-94w6) | CRITICAL | AnyIO: TLSStream IDNA 2003 host name encoding enables potential TLS certificate spoofing |
| mcp | [GHSA-84m7-p3x7-pcfv](https://osv.dev/vulnerability/GHSA-84m7-p3x7-pcfv) | MODERATE | MCP Python SDK: Unbounded Session Accumulation in StreamableHTTP Transport Enables Resource Exhaustion |
| pyjwt | [GHSA-8wjv-2p76-3863](https://osv.dev/vulnerability/GHSA-8wjv-2p76-3863) | MODERATE | PyJWT: Uncaught RecursionError in jwt.decode() on deeply nested token header |
| pyjwt | [GHSA-9j54-fg26-wv3r](https://osv.dev/vulnerability/GHSA-9j54-fg26-wv3r) | HIGH | PyJWT: PyJWK accepts empty HMAC keys, bypassing PyJWT's empty-key validation |
| pyjwt | [GHSA-9v7f-9g4p-ffgj](https://osv.dev/vulnerability/GHSA-9v7f-9g4p-ffgj) | HIGH | PyJWT: PyJWKClient follows redirects when fetching JWKS |
| picomatch | [GHSA-fc5q-39xc-vjpf](https://osv.dev/vulnerability/GHSA-fc5q-39xc-vjpf) | HIGH | picomatch vulnerable to ReDoS through single-branch repeated extglobs |
| pyjwt | [GHSA-ffc3-869f-jxw9](https://osv.dev/vulnerability/GHSA-ffc3-869f-jxw9) | CRITICAL | PyJWT: Asymmetric-PEM detection bypass: whitespace/line-ending-mutated public keys skip the HS/asymmetric confusion guard |
| cryptography | [GHSA-g6cj-pr64-35w5](https://osv.dev/vulnerability/GHSA-g6cj-pr64-35w5) | HIGH | cryptography: PKCS#7 EnvelopedData decryption exposes a Bleichenbacher oracle through distinguishable errors and timing |
| pyjwt | [GHSA-gvp8-978c-rx2q](https://osv.dev/vulnerability/GHSA-gvp8-978c-rx2q) | MODERATE | PyJWT.decode() reintroduces options-dict mutation, enabling silent claim-verification bypass on dict reuse |
| uv | [GHSA-hq85-5cpj-mr62](https://osv.dev/vulnerability/GHSA-hq85-5cpj-mr62) | CRITICAL | uv's bundled CA store trusts an emSign root whose intermediate CA keys are compromised |
| pyjwt | [GHSA-hxm8-2xgr-2p9m](https://osv.dev/vulnerability/GHSA-hxm8-2xgr-2p9m) | MODERATE | PyJWT: Non-canonical signature segments enable raw-token revocation bypass |
| pyjwt | [GHSA-jwrc-g2q2-pq5p](https://osv.dev/vulnerability/GHSA-jwrc-g2q2-pq5p) | MODERATE | PyJWT: ReDoS vulnerability when calling the `is_pem_format` function. |
| pyjwt | [GHSA-p4g4-x82p-q773](https://osv.dev/vulnerability/GHSA-p4g4-x82p-q773) | HIGH | PyJWT: Public keys in DER form are accepted as HMAC secrets, bypassing the CVE-2022-29217 guard |
| uv | [GHSA-pjjw-68hj-v9mw](https://osv.dev/vulnerability/GHSA-pjjw-68hj-v9mw) | LOW | uv vulnerable to arbitrary file deletion through RECORD entries |
| pyjwt | [GHSA-pxh4-856f-4h89](https://osv.dev/vulnerability/GHSA-pxh4-856f-4h89) | HIGH | PyJWT: HS256/384/512 verify accepts empty HMAC key via oct JWK (PyJWK/PyJWKClient) enabling token forgery |
| pyjwt | [GHSA-r6x4-923q-g947](https://osv.dev/vulnerability/GHSA-r6x4-923q-g947) | HIGH | PyJWT BOM Bypass |
| mcp | [GHSA-rwrf-2pqf-9j8j](https://osv.dev/vulnerability/GHSA-rwrf-2pqf-9j8j) | MODERATE | Model Context Protocol Python SDK: Client fetched server-chosen $ref URLs while validating tool results against output schemas |
| pyjwt | [GHSA-w2cx-738m-mc7w](https://osv.dev/vulnerability/GHSA-w2cx-738m-mc7w) | HIGH | PyJWT accepts public JWK containers as HMAC secrets |
| mcp | [GHSA-w4fh-qvv9-3v23](https://osv.dev/vulnerability/GHSA-w4fh-qvv9-3v23) | MODERATE | Model Context Protocol Python SDK: Server bearer-token authentication accepts tokens issued for a different resource server |
| pyjwt | [GHSA-w6j9-cwv2-h6wq](https://osv.dev/vulnerability/GHSA-w6j9-cwv2-h6wq) | MODERATE | PyJWT: Malformed RSA JWK aborts parsing of an entire JWK Set |
| pyjwt | [GHSA-x33g-cr3x-6449](https://osv.dev/vulnerability/GHSA-x33g-cr3x-6449) | MODERATE | PyJWT accepts inconsistent OKP x/d JWKs, causing public/private key identity confusion |
