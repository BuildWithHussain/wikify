# SQLite Graph Load

This phase uses a simple Beagle-style graph stored in SQLite.

The graph is for parsed document structure and provenance only. It is not a
semantic vector index.

## Core idea

Store parser facts as nodes, edges, and observations.

```text
document
  -> page
    -> block
      -> section
```

Every derived relationship should keep enough provenance to explain why it
exists: parser provider, parse run, confidence, source page, and source bbox
where available.

Current implementation note: when a run parses a page subset, `documents`
stores the full PDF page count and `nodes` stores page nodes only for parsed
canonical pages.

## Tables

### documents

```sql
CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  page_count INTEGER,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);
```

### parse_runs

```sql
CREATE TABLE parse_runs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  profile_name TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT,
  config_json TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  duration_ms INTEGER,
  cost_usd REAL,
  status TEXT NOT NULL,
  error TEXT,
  FOREIGN KEY (document_id) REFERENCES documents(id)
);
```

### nodes

```sql
CREATE TABLE nodes (
  id TEXT PRIMARY KEY,
  parse_run_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  type TEXT NOT NULL,
  label TEXT,
  text TEXT,
  markdown TEXT,
  page_number INTEGER,
  bbox_json TEXT,
  confidence REAL,
  metadata_json TEXT,
  FOREIGN KEY (parse_run_id) REFERENCES parse_runs(id),
  FOREIGN KEY (document_id) REFERENCES documents(id)
);
```

Node types:

```text
document
page
block
section
table
image
```

### edges

```sql
CREATE TABLE edges (
  id TEXT PRIMARY KEY,
  parse_run_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  source_node_id TEXT NOT NULL,
  target_node_id TEXT NOT NULL,
  type TEXT NOT NULL,
  confidence REAL,
  evidence_json TEXT,
  metadata_json TEXT,
  FOREIGN KEY (parse_run_id) REFERENCES parse_runs(id),
  FOREIGN KEY (document_id) REFERENCES documents(id),
  FOREIGN KEY (source_node_id) REFERENCES nodes(id),
  FOREIGN KEY (target_node_id) REFERENCES nodes(id)
);
```

Edge types:

```text
DOCUMENT_HAS_PAGE
PAGE_HAS_BLOCK
BLOCK_PART_OF_SECTION
SECTION_HAS_TABLE
SECTION_HAS_IMAGE
RUN_PRODUCED_NODE
```

### observations

Raw parser claims should be preserved separately from normalized graph facts.

```sql
CREATE TABLE observations (
  id TEXT PRIMARY KEY,
  parse_run_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  subject_id TEXT,
  observation_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  confidence REAL,
  page_number INTEGER,
  bbox_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (parse_run_id) REFERENCES parse_runs(id),
  FOREIGN KEY (document_id) REFERENCES documents(id)
);
```

This allows us to improve sectioning, heading correction, table merging, or
classification later without reparsing the PDF.

### assets

```sql
CREATE TABLE assets (
  id TEXT PRIMARY KEY,
  parse_run_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  node_id TEXT,
  type TEXT NOT NULL,
  path TEXT NOT NULL,
  mime_type TEXT,
  page_number INTEGER,
  bbox_json TEXT,
  metadata_json TEXT,
  FOREIGN KEY (parse_run_id) REFERENCES parse_runs(id),
  FOREIGN KEY (document_id) REFERENCES documents(id),
  FOREIGN KEY (node_id) REFERENCES nodes(id)
);
```

## Helpful indexes

```sql
CREATE INDEX idx_nodes_run_type ON nodes(parse_run_id, type);
CREATE INDEX idx_nodes_doc_page ON nodes(document_id, page_number);
CREATE INDEX idx_edges_run_type ON edges(parse_run_id, type);
CREATE INDEX idx_edges_source ON edges(source_node_id);
CREATE INDEX idx_edges_target ON edges(target_node_id);
CREATE INDEX idx_observations_run_type ON observations(parse_run_id, observation_type);
```

## Optional FTS

FTS is allowed in this phase because it is lexical search, not vector search.
It helps inspect loaded outputs.

```sql
CREATE VIRTUAL TABLE node_fts USING fts5(
  node_id UNINDEXED,
  text,
  markdown,
  label
);
```

Status: optional and not implemented in the first checkpoint.

## Example queries

List sections for a document:

```sql
SELECT id, label, page_number, confidence
FROM nodes
WHERE document_id = :document_id
  AND parse_run_id = :parse_run_id
  AND type = 'section'
ORDER BY page_number, id;
```

Find all blocks in a section:

```sql
SELECT b.*
FROM edges e
JOIN nodes b ON b.id = e.source_node_id
WHERE e.target_node_id = :section_node_id
  AND e.type = 'BLOCK_PART_OF_SECTION'
ORDER BY b.page_number, json_extract(b.metadata_json, '$.reading_order');
```

Inspect parser warnings:

```sql
SELECT *
FROM observations
WHERE parse_run_id = :parse_run_id
  AND observation_type = 'warning'
ORDER BY page_number;
```

## Later additions

Do not add these in the parse/load phase:

- chunk nodes
- semantic tags
- embeddings
- vector indexes
- retrieval traces
- chat messages
