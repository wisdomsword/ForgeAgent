## Context

The audit identifies specific versions and one npm advisory with no published compatible fix.

## Decisions

- Update only the affected Python packages and keep MCP on 1.x.
- Reuse the uv lock for audit targets and constrain the build environment through pyproject.
- Install OpenSpec from an npm lock with lifecycle scripts disabled. Audit the tree separately and fail on new advisories, audit errors, and an expired exception.
- Keep third-party license texts with their own distributions and document additional obligations when redistributing them.
