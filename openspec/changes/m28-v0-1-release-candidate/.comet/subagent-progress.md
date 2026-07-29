# M28 Subagent Progress

- Plan task: Task 3: RC 发布说明与限制合同
- OpenSpec tasks: 4.1, 4.2
- Phase: done
- Review mode: thorough
- Review/fix round: 1/2
- Base commit: 44125e5
- Implementer: DONE
- Implementation commit: 03e1983
- RED/GREEN evidence: docs contract RED 4 failed; GREEN docs/adjacent 21 passed; Ruff/format/diff passed.
- Changed files: `docs/releases/0.1.0-rc.md`, `README.md`, `docs/platform-support.md`, `tests/test_m28_release_docs.py`
- Review findings: Important -- unqualified "no public resume API" contradicts public Loop resume request support; evidence tests do not bind configured/historical statuses to their exact M28/M24 rows and permit contradictory verified claims. Minor -- duplicate 0.1.0 RC entry is not rejected.
- Fix strategy: narrow wording to no collaboration-specific resume endpoint; parse exact evidence rows/sections, forbid contradictory M28 verified/pass claims, and assert a single 0.1.0 RC entry file.
- Fix commit: `887608e`; RED strict contracts 2 failed/2 passed; GREEN adjacent 21 passed; Ruff/format/diff passed.
- Review result: Spec passed; no blocking finding. Resume wording, exact evidence rows, contradiction guard, and unique RC entry all approved.
- Requirements artifact: `.superpowers/sdd/task-3-brief.md`
- Evidence boundary: M24 Pipeline 50 / Job 249 is historical container-only evidence; M28 installed-wheel required job remains configured/pending until a new run exists.
