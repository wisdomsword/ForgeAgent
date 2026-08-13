## ADDED Requirements

### Requirement: Directory image input fails loudly for recognized oversized images

When scanning a directory, the system SHALL fail the entire image load if any file is recognized as a supported image format and exceeds the per-image byte limit. The resulting validation error SHALL identify the offending file.

#### Scenario: A directory contains an oversized PNG

- **WHEN** a directory contains a PNG whose size exceeds the per-image limit
- **THEN** image loading raises a validation error naming that PNG

### Requirement: Oversized non-images remain skippable without full reads

When scanning a directory, the system SHALL skip an oversized file whose bounded header is not a supported image format, without reading its complete contents.

#### Scenario: A directory contains a large binary file and a small PNG

- **WHEN** image loading scans a directory containing an oversized non-image and a valid PNG
- **THEN** it returns the PNG and does not fully read the non-image
