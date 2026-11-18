# Security policy

## Supported versions

| Version | Security maintenance |
| --- | --- |
| 0.1.0 Release Candidate / current development checkout | Fixes are made on the current development branch; update to its latest reviewed revision. |
| Older revisions | No maintained release branch or backported security fixes. |

ForgeAgent has not published a stable release or a PyPI package. A historical passing
candidate does not verify a later checkout. See the [platform evidence](docs/platform-support.md)
and [threat model](docs/threat-model.md) for the scope of tested environments.

## Reporting a vulnerability

Use GitHub **Private vulnerability reporting** from the repository's Security tab when
it is enabled. If that option is unavailable, email the maintainer privately at
[liu.mingling@gmail.com](mailto:liu.mingling@gmail.com), the contact recorded in
[LICENSE](LICENSE). Do not disclose an unfixed vulnerability in a public issue.

Include the affected revision, operating system, sandbox tier, prerequisites, impact,
and a minimal reproduction with fake credentials and disposable files. Do not send
real keys, private task transcripts, or user data. No response-time guarantee is made.

## Execution boundaries

Generated programs execute code. The default restricted tier is application-level
protection, not an OS-level sealed sandbox. Trusted execution runs in the host process;
use it only for reviewed code. Container isolation requires a supported Docker daemon.
MCP servers execute in the host process, and approvals do not make an untrusted server
safe. The optional HTTP control plane remains loopback-only and does not provide TLS.
Keep credentials, receipts, durable task state, Memory, and backups private. Review
[docs/threat-model.md](docs/threat-model.md) before granting wider filesystem access
or configuring MCP integrations.
