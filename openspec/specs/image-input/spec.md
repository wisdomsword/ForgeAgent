# image-input Specification

## Purpose
定义命令行与 REPL 图片输入的大小限制、目录扫描与超限失败语义。已识别图片超过大小上限时，目录输入必须整体失败并指出相关文件，不能静默丢弃图片后继续发送不完整输入。

## Requirements

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

### Requirement: Directory image limits apply during loading
Directory image loading MUST stop after detecting the first image beyond the request count limit rather than accumulating all images.

#### Scenario: Directory contains more than twenty images
- **WHEN** a directory contains twenty-one or more recognized images
- **THEN** loading fails with the existing count-limit diagnostic without loading subsequent images
