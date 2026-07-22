# M17 Subagent Progress

- Plan task: Task 6 complete: Provider-normalized prompt denominator 已交付
- OpenSpec mapping: 4.1 provider-normalized total prompt denominator
- Phase: done
- Base commit: 609f05bdb4d01060c03ce38dfa540cacdf4089e1
- Implementation commits: 483964d761645405365b0a5bceb5b34225b5f54d; 437a8d4
- Changed files: src/forgeagent/models.py; src/forgeagent/anthropic_client.py; src/forgeagent/openai_compatible_client.py; tests/test_anthropic_client.py; tests/test_openai_compatible_client.py; tests/test_streaming.py
- TDD RED: 4 failed as expected because total_prompt_tokens was absent
- TDD GREEN: focused 4 passed; edge matrix 8 passed; provider regression 79 passed; Ruff/diff check passed
- Diff size: 117 insertions
- Review mode: standard
- Risk review triggered: yes
- Risk signals: cross-provider adapter contract; internal model schema; streaming and non-streaming paths
- Review/fix round: 1/1
- Review result: re-review spec PASS; quality APPROVED
- Open findings: none
