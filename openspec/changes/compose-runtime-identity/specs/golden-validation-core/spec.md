## MODIFIED Requirements

### Requirement: Golden catalog has one exact ID universe
The candidate catalog SHALL contain each and only each ID from `G01` through `G400`, inclusive. The trusted core SHALL remain the exact existing 20-ID set; its complement SHALL contain exactly 380 non-core candidates. Validation MUST reject duplicate, missing, additional or substituted catalog IDs before any claim about core or candidate counts.

The complete `G01` through `G400` unique, continuous and 380-item non-core check SHALL be owned by the documentation-consistency pytest gate, not by the production golden runner preflight. The twenty M15 additions SHALL use IDs G381-G400 and SHALL preserve the catalog-wide 40/25/20/10/5 category distribution by adding exactly 8 file/data, 5 Python execution/sandbox, 4 code modification, 2 network/API and 1 system-query scenario.

#### Scenario: Candidate ID universe is exact
- **WHEN** catalog consistency validation reads the candidate documentation and trusted-core manifest
- **THEN** it accepts only the unique inclusive `G01` through `G400` universe, exactly 20 core IDs and exactly 380 non-core IDs, with the complete catalog retaining the exact approved category distribution

### Requirement: Candidate catalog is not presented as validated
ForgeAgent documentation SHALL distinguish the 20 executable trusted-core scenarios from the remaining candidate task catalog and MUST NOT describe candidates as validated without executable evidence. M15 identity behavior SHALL use dedicated deterministic pytest/mock-replay evidence; merely adding G381-G400 definitions to the candidate catalog SHALL NOT count as execution evidence.

#### Scenario: User reads golden task documentation
- **WHEN** documentation lists the wider task catalog after the M15 extension
- **THEN** it labels exactly 20 scenarios as executable trusted core and exactly 380 other IDs in the `G01` through `G400` universe as non-core candidates
