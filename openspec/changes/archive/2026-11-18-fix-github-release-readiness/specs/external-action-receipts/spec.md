## ADDED Requirements

### Requirement: Receipt authority is protected from task tools
ForgeAgent MUST prevent model-driven file and execution tools from modifying, removing, moving, or replacing receipt storage or its ancestor bindings in restricted and container tiers. Registered receipt loss MUST fail closed across restart. Existing valid receipts MUST be preserved without dispatch during initialization.

#### Scenario: Model attempts to delete an unknown receipt
- **WHEN** task code or a file tool targets a receipt or renames an ancestor
- **THEN** the operation is denied and the unknown action remains pending

#### Scenario: Registered receipt disappears
- **WHEN** a registered receipt is absent during listing, startup, or new action preparation
- **THEN** the store reports an error and no related external action is dispatched

#### Scenario: Existing receipts are adopted
- **WHEN** the protected store opens valid legacy records without a directory index
- **THEN** it preserves their bytes and phases and records their identities without replay
