## ADDED Requirements

### Requirement: Directory image limits apply during loading
Directory image loading MUST stop after detecting the first image beyond the request count limit rather than accumulating all images.

#### Scenario: Directory contains more than twenty images
- **WHEN** a directory contains twenty-one or more recognized images
- **THEN** loading fails with the existing count-limit diagnostic without loading subsequent images
