"""SQLite graph store (beagle-style: typed nodes + edges, evidence on every node).

Schema:
  documents   - one row per uploaded PDF + run metadata
  nodes       - type in {document, section}; page_start/end = citation/evidence
  edges       - rel in {HAS_SECTION, PART_OF}
  page_scores - per-page verification results

"All job descriptions across all PDFs" is just:
  SELECT * FROM nodes WHERE section_type = 'job_description'
deterministic, complete, each row self-citing. No vectors.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    page_count INTEGER,
    parser_used TEXT,
    status TEXT,
    mean_score REAL,
    source_path TEXT
);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT,
    section_type TEXT,
    hierarchy_path TEXT,
    page_start INTEGER,
    page_end INTEGER,
    markdown TEXT,
    parent_id TEXT,
    FOREIGN KEY (doc_id) REFERENCES documents(id)
);
CREATE TABLE IF NOT EXISTS edges (
    src_id TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    rel TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page_scores (
    doc_id TEXT NOT NULL,
    page_no INTEGER NOT NULL,
    text_recall REAL,
    extra_ratio REAL,
    table_score REAL,
    judge_score REAL,
    composite REAL,
    verdict TEXT,
    notes TEXT,
    kind TEXT
);
CREATE TABLE IF NOT EXISTS escalations (
    doc_id TEXT NOT NULL,
    page_no INTEGER NOT NULL,
    parser TEXT,
    text_recall REAL,
    extra_ratio REAL,
    table_score REAL,
    judge_score REAL,
    composite REAL,
    verdict TEXT,
    notes TEXT,
    adopted INTEGER DEFAULT 0,
    PRIMARY KEY (doc_id, page_no)
);
CREATE TABLE IF NOT EXISTS wiki_pages (
    doc_id TEXT NOT NULL,
    slug TEXT NOT NULL,
    title TEXT,
    ordinal INTEGER,
    page_start INTEGER,
    page_end INTEGER,
    markdown TEXT,
    ref_links INTEGER,
    PRIMARY KEY (doc_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_nodes_doc ON nodes(doc_id);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(section_type);
CREATE INDEX IF NOT EXISTS idx_scores_doc ON page_scores(doc_id);
"""


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
        con.executescript(_SCHEMA)
        # Best-effort migration for dbs created before source_path existed.
        cols = {r["name"] for r in con.execute("PRAGMA table_info(documents)")}
        if "source_path" not in cols:
            con.execute("ALTER TABLE documents ADD COLUMN source_path TEXT")
        pcols = {r["name"] for r in con.execute("PRAGMA table_info(page_scores)")}
        if "kind" not in pcols:
            con.execute("ALTER TABLE page_scores ADD COLUMN kind TEXT")
        ecols = {r["name"] for r in con.execute("PRAGMA table_info(escalations)")}
        if "adopted" not in ecols:
            con.execute("ALTER TABLE escalations ADD COLUMN adopted INTEGER DEFAULT 0")


# ---- writes -------------------------------------------------------------

def create_document(doc_id, filename, uploaded_at, page_count, parser_used, status, source_path=None):
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO documents "
            "(id, filename, uploaded_at, page_count, parser_used, status, mean_score, source_path) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, filename, uploaded_at, page_count, parser_used, status, None, source_path),
        )
        # the document node itself
        con.execute(
            "INSERT OR REPLACE INTO nodes (id, doc_id, type, title) VALUES (?,?,?,?)",
            (f"doc:{doc_id}", doc_id, "document", filename),
        )


def finish_document(doc_id, status, mean_score):
    with _conn() as con:
        con.execute(
            "UPDATE documents SET status=?, mean_score=? WHERE id=?",
            (status, mean_score, doc_id),
        )


def add_section(node_id, doc_id, section, parent_id):
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO nodes "
            "(id, doc_id, type, title, section_type, hierarchy_path, "
            "page_start, page_end, markdown, parent_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                node_id, doc_id, "section", section.title, section.section_type,
                " > ".join(section.hierarchy_path), section.page_start,
                section.page_end, section.markdown, parent_id,
            ),
        )
        con.execute(
            "INSERT INTO edges (src_id, dst_id, rel) VALUES (?,?,?)",
            (f"doc:{doc_id}", node_id, "HAS_SECTION"),
        )
        if parent_id:
            con.execute(
                "INSERT INTO edges (src_id, dst_id, rel) VALUES (?,?,?)",
                (node_id, parent_id, "PART_OF"),
            )


def add_page_score(doc_id, ps):
    with _conn() as con:
        con.execute(
            "INSERT INTO page_scores (doc_id, page_no, text_recall, extra_ratio, "
            "table_score, judge_score, composite, verdict, notes, kind) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                doc_id, ps.page_no, ps.text_recall, ps.extra_ratio, ps.table_score,
                ps.judge_score, ps.composite, ps.verdict, "; ".join(ps.notes), ps.kind,
            ),
        )


def add_escalation(doc_id, parser, ps, adopted=False):
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO escalations (doc_id, page_no, parser, text_recall, "
            "extra_ratio, table_score, judge_score, composite, verdict, notes, adopted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                doc_id, ps.page_no, parser, ps.text_recall, ps.extra_ratio, ps.table_score,
                ps.judge_score, ps.composite, ps.verdict, "; ".join(ps.notes), int(adopted),
            ),
        )


def get_escalations(doc_id):
    with _conn() as con:
        return {
            r["page_no"]: dict(r)
            for r in con.execute("SELECT * FROM escalations WHERE doc_id=?", (doc_id,))
        }


def update_page_score(doc_id, ps):
    with _conn() as con:
        con.execute(
            "UPDATE page_scores SET text_recall=?, extra_ratio=?, table_score=?, "
            "judge_score=?, composite=?, verdict=?, notes=?, kind=? WHERE doc_id=? AND page_no=?",
            (
                ps.text_recall, ps.extra_ratio, ps.table_score, ps.judge_score,
                ps.composite, ps.verdict, "; ".join(ps.notes), ps.kind, doc_id, ps.page_no,
            ),
        )


def canonical_mean(doc_id):
    """Mean of the canonical score per page: the remediation when it was adopted, else baseline."""
    base = {s["page_no"]: s["composite"] for s in get_page_scores(doc_id)}
    esc = get_escalations(doc_id)
    if not base:
        return 0.0
    best = [esc[p]["composite"] if (p in esc and esc[p]["adopted"]) else c for p, c in base.items()]
    return round(sum(best) / len(best), 3)


def clear_sections(doc_id):
    """Drop a doc's section nodes + their edges (keep the document node)."""
    with _conn() as con:
        con.execute("DELETE FROM nodes WHERE doc_id=? AND type='section'", (doc_id,))
        con.execute(
            "DELETE FROM edges WHERE src_id=? OR src_id LIKE ? OR dst_id LIKE ?",
            (f"doc:{doc_id}", f"{doc_id}:%", f"{doc_id}:%"),
        )


def set_section_type(node_id, stype):
    with _conn() as con:
        con.execute("UPDATE nodes SET section_type=? WHERE id=?", (stype, node_id))


def mean_composite(doc_id):
    with _conn() as con:
        r = con.execute(
            "SELECT AVG(composite) a FROM page_scores WHERE doc_id=?", (doc_id,)
        ).fetchone()
        return round(r["a"], 3) if r and r["a"] is not None else 0.0


# ---- reads --------------------------------------------------------------

def list_documents():
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM documents ORDER BY uploaded_at DESC")]


def get_document(doc_id):
    with _conn() as con:
        row = con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None


def get_page_scores(doc_id):
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM page_scores WHERE doc_id=? ORDER BY page_no", (doc_id,))]


def get_sections(doc_id, section_type=None):
    q = "SELECT * FROM nodes WHERE type='section' AND doc_id=?"
    params = [doc_id]
    if section_type:
        q += " AND section_type=?"
        params.append(section_type)
    q += " ORDER BY page_start, id"
    with _conn() as con:
        return [dict(r) for r in con.execute(q, params)]


def sections_by_type(section_type):
    """Cross-document traversal — the headline query."""
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT n.*, d.filename FROM nodes n JOIN documents d ON n.doc_id=d.id "
            "WHERE n.type='section' AND n.section_type=? ORDER BY d.filename, n.page_start",
            (section_type,))]


def clear_wiki(doc_id):
    with _conn() as con:
        con.execute("DELETE FROM wiki_pages WHERE doc_id=?", (doc_id,))


def add_wiki_page(doc_id, wp):
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO wiki_pages "
            "(doc_id, slug, title, ordinal, page_start, page_end, markdown, ref_links) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, wp["slug"], wp["title"], wp["ordinal"], wp["page_start"],
             wp["page_end"], wp["markdown"], wp["ref_links"]),
        )


def list_wiki_pages(doc_id):
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM wiki_pages WHERE doc_id=? ORDER BY ordinal", (doc_id,))]


def get_wiki_page(doc_id, slug):
    with _conn() as con:
        r = con.execute(
            "SELECT * FROM wiki_pages WHERE doc_id=? AND slug=?", (doc_id, slug)).fetchone()
        return dict(r) if r else None


def section_type_counts():
    with _conn() as con:
        return {r["section_type"]: r["c"] for r in con.execute(
            "SELECT section_type, COUNT(*) c FROM nodes "
            "WHERE type='section' AND section_type IS NOT NULL GROUP BY section_type")}
