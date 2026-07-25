## MODIFIED Requirements

### Requirement: File tool path boundaries are root-safe and minimally disclosing
ForgeAgent MUST evaluate canonical WebFetch artifact and file-tool targets with a containment predicate that accepts the root itself and all real descendants, including when `allowed_root` is the filesystem root, and MUST NOT disclose model or host absolute paths in failure outcomes. FileWrite MUST perform its final parent traversal and target open relative to a bound project-root directory descriptor, MUST NOT follow symlinks in any traversed component or the final target, and MUST fail closed if the bound root or traversed directory is replaced before the write completes.

#### Scenario: Filesystem root is the allowed root
- **WHEN** a file tool or restricted audit hook evaluates a target below `allowed_root="/"`
- **THEN** the target is treated as contained instead of being rejected by a doubled-separator prefix check

#### Scenario: A file tool receives an invalid path
- **WHEN** FileRead, FileWrite or FileList receives a syntactically invalid path such as one containing NUL
- **THEN** the tool returns its structured fixed failure outcome and does not propagate `ValueError`

#### Scenario: FileRead or FileList fails on a host path
- **WHEN** FileRead or FileList rejects an out-of-root target or receives a filesystem error whose text contains an absolute path
- **THEN** it returns the fixed detail `FileRead failed` or `FileList failed` without the model path, canonical root or exception text

#### Scenario: Non-trusted FileRead records a sanitized audit path
- **WHEN** restricted or container FileRead has a confirmer and receives an absolute in-root model path containing a known secret or non-canonical components
- **THEN** after successful path validation it preserves the normal FileRead result, does not call the confirmer or console, and emits one Python logger INFO audit containing only the known-secret-masked canonical project-relative path, without the raw model path, absolute root or secret

#### Scenario: Rejected FileRead path is not audited
- **WHEN** non-trusted FileRead receives a syntactically invalid or out-of-root path
- **THEN** it returns the fixed `FileRead failed` result and emits no path-bearing audit record, so the raw input, canonical root and known secret are not logged

#### Scenario: FileWrite target becomes a symlink after validation
- **WHEN** a FileWrite target or one of its parent components is replaced with a symlink after canonical validation but before the final descriptor-relative open
- **THEN** ForgeAgent returns the fixed `FileWrite failed` result and leaves every outside target unchanged

#### Scenario: FileWrite project-root binding changes during the write
- **WHEN** the pathname of the canonical project root is replaced after ForgeAgent opens its root directory descriptor
- **THEN** ForgeAgent fails the operation instead of reporting a successful write through a stale or attacker-controlled pathname
