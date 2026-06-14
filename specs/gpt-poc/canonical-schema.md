# Canonical Document Schema

The canonical schema is the contract between parser adapters and every
downstream step.

It should preserve source grounding. A parsed heading, paragraph, table, or
image is only useful if we can trace it back to a page and bounding box where
available.

## Top-level shape

```json
{
  "schema_version": "0.1",
  "document": {
    "id": "doc_...",
    "filename": "sample.pdf",
    "sha256": "...",
    "page_count": 100,
    "metadata": {}
  },
  "parse_run": {
    "id": "run_...",
    "profile_name": "docling_local",
    "provider": "docling",
    "model": "default",
    "started_at": "2026-06-14T00:00:00Z",
    "duration_ms": 12345,
    "cost_usd": null,
    "config": {}
  },
  "pages": [],
  "sections": [],
  "assets": [],
  "warnings": []
}
```

`document.page_count` is the full source PDF page count when the adapter can
inspect the PDF. If a run uses `page_range` or CLI `--pages`, the top-level
`pages` array contains only the parsed pages for that run.

## Page

```json
{
  "id": "page_001",
  "page_number": 1,
  "width": 612,
  "height": 792,
  "rotation": 0,
  "blocks": []
}
```

## Block

```json
{
  "id": "block_001",
  "page_id": "page_001",
  "type": "heading",
  "text": "Job Description",
  "markdown": "## Job Description",
  "level": 2,
  "bbox": [48, 92, 520, 128],
  "confidence": 0.94,
  "reading_order": 7,
  "source": {
    "provider": "openrouter",
    "raw_id": "..."
  },
  "metadata": {}
}
```

Allowed `type` values:

```text
heading
paragraph
list
list_item
table
image
formula
footer
header
page_number
unknown
```

## Table block

Tables should keep both a renderable representation and structured cell data
when possible.

```json
{
  "id": "block_010",
  "type": "table",
  "markdown": "<table>...</table>",
  "table": {
    "format": "html",
    "rows": 5,
    "columns": 4,
    "cells": [
      {
        "row": 0,
        "column": 0,
        "rowspan": 1,
        "colspan": 2,
        "text": "Role",
        "bbox": [40, 100, 180, 120]
      }
    ]
  }
}
```

Use HTML table rendering when markdown tables would lose merged-cell or nested
structure.

## Section

Sections are derived from blocks, not directly from parser output unless the
provider has a reliable native section model.

```json
{
  "id": "section_001",
  "title": "Job Description",
  "heading_path": ["Role", "Job Description"],
  "level": 2,
  "page_start": 3,
  "page_end": 5,
  "block_ids": ["block_010", "block_011", "block_012"],
  "markdown": "## Job Description\n...",
  "confidence": 0.88,
  "metadata": {}
}
```

## Asset

```json
{
  "id": "asset_001",
  "type": "page_image",
  "page_id": "page_001",
  "path": "runs/sample/docling_local/assets/page_001.png",
  "mime_type": "image/png",
  "bbox": null,
  "metadata": {}
}
```

## Warning

Warnings are first-class because parser failures are expected during a bakeoff.

```json
{
  "code": "missing_bbox",
  "severity": "info",
  "message": "Provider did not return bounding boxes for paragraph blocks.",
  "page_number": 4,
  "block_id": "block_123"
}
```

## Required invariants

- `document.sha256` must be stable for the file content.
- `document.page_count` should remain stable for the source file even when only
  a sampled page range is parsed.
- `parse_run.config` must contain the effective profile after defaults.
- block ids must be unique within a parse run.
- every block must point to a page.
- section `block_ids` must refer to existing blocks.
- every markdown fragment should be reproducible from canonical blocks.
- parser-specific data belongs in `metadata` or raw output files, not in the
  core schema.
