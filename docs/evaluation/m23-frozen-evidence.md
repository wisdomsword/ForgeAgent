# Portable M23 historical evidence

[The frozen manifest](../../tests/data/m23-frozen-evidence.json) replaces tests that
required Git objects removed by history rewriting. It is evidence of historical
content, not a claim that the current runtime matches the M23 runtime.

The manifest was captured from checkout `8a306475212e60eb571ad6a80635507ac1610d44`.
The surviving rewritten history supplied M23's pre-change base
`9bf333ab264a05fd4e7bafbed53df4035e5a12e0` (`114680a^`) and archive
`ed29147b3f485120d9461d5b8e733d7a627d854e`. Their collaboration runtime, CLI,
model registry, pyproject, and lockfile were read with `git show`; all five pairs
were independently hashed with SHA-256 and were identical. `git diff` across
those five paths was also empty. Both digest maps are retained in the manifest.
The tests pin the SHA-256 of the whole manifest, so editing its recorded result
requires an explicit baseline change.

The manifest additionally contains the path and SHA-256 of all 62 tracked M23
protocol/evidence files from this checkout, including the invalid first run's
audit trail. The M25 contract recomputes both the exact inventory and every digest
from files on disk. Missing, added, or modified published evidence fails; only
the two already ignored local runs named in `.gitignore` remain outside the
published audit. Tests neither require `.git` nor query any historical objects.

The formal raw records are still independently recomputed into the checked-in
summary and report by the existing M25 tests. No historical protocol, raw record,
summary, report, or runtime file was changed to create this manifest.
