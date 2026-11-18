## Why

The dependency audit found affected Python runtime packages, an affected CI installer, and an unpinned build and OpenSpec dependency graph. Release verification needs to detect new advisories and retain third-party license obligations.

## What Changes

- Upgrade the affected Python packages and declare the supported MCP version floor.
- Pin CI and build tools. Scan the locked Python and npm packages as a separate CI job.
- Verify the MCP client resolves local schema references without enabling external retrieval.
- Explain redistribution requirements and record the time-limited OpenSpec advisory exception.

## Capabilities

### New Capabilities

### Modified Capabilities

- `continuous-verification`: audit dependency graphs and bound known toolchain exceptions.

## Impact

Affects package metadata, locks, CI, MCP regression coverage, and distribution documentation.
