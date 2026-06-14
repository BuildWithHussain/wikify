CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  page_count INTEGER,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parse_runs (
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

CREATE TABLE IF NOT EXISTS nodes (
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

CREATE TABLE IF NOT EXISTS edges (
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

CREATE TABLE IF NOT EXISTS observations (
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

CREATE TABLE IF NOT EXISTS assets (
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

CREATE TABLE IF NOT EXISTS page_reviews (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  page_type TEXT,
  winning_parse_run_id TEXT,
  rejected_parse_run_ids_json TEXT NOT NULL DEFAULT '[]',
  rejection_reason TEXT,
  status TEXT NOT NULL DEFAULT 'unreviewed',
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (document_id, page_number),
  FOREIGN KEY (document_id) REFERENCES documents(id),
  FOREIGN KEY (winning_parse_run_id) REFERENCES parse_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_nodes_run_type ON nodes(parse_run_id, type);
CREATE INDEX IF NOT EXISTS idx_nodes_doc_page ON nodes(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_edges_run_type ON edges(parse_run_id, type);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_observations_run_type ON observations(parse_run_id, observation_type);
CREATE INDEX IF NOT EXISTS idx_page_reviews_doc_status ON page_reviews(document_id, status);
