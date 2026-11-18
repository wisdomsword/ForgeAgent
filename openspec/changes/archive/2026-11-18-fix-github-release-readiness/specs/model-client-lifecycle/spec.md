## ADDED Requirements

### Requirement: Provider attempts have one retry owner
Provider SDK retries MUST be disabled when ForgeAgent owns retries, so reported attempts correspond to actual transport requests.

#### Scenario: Provider repeatedly rate limits
- **WHEN** all configured attempts receive retryable rate-limit responses
- **THEN** the number of HTTP requests equals the reported attempt count

### Requirement: Discovery is bounded and cache failures degrade safely
Model discovery MUST use an explicit finite short timeout, close its SDK resources, validate cached provider/model mappings, and save cache data atomically. Invalid or unreadable caches MUST behave as a cache miss without crashing or returning non-string model IDs.

#### Scenario: Cache contains valid JSON of the wrong shape
- **WHEN** the cache root, provider entry, or model ID value has an invalid type
- **THEN** resolution safely discovers or falls back to the requested logical model ID
