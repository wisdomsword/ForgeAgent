# Safe dependency-state Loop example

Goal: inspect and report the project's current dependency state without modifying it.

Suggested Loop goal:

```text
Read the project dependency manifests and lockfiles that already exist. Write a concise
dependency-state report with observed package names and pinned versions. Leave all
dependencies unchanged; do not create a branch; do not commit, push, or open a PR.
After each independently verified reporting section, call Checkpoint with the section
as completed and a concise handoff. Finish only after the report is written.
```

Start with an explicit bounded budget:

```bash
uv run forgeagent loop "Read dependency manifests and report their current state only." \
  --token-budget 12000 --max-rounds 20 --wall-clock-seconds 900
```

If interrupted after a successful Checkpoint commit, resume the same frozen goal:

```bash
uv run forgeagent loop --resume LOOP_ID
```

The checkpoint commit makes completed report sections durable. Work after the latest
commit can replay, so the task remains report-only and has no package, Git, or remote
side effects.
