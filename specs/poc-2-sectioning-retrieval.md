# POC-2 — Sectioning, Tagging & Retrieval

**Purpose:** turn the winning parser's markdown into a queryable knowledge base
that answers cross-document questions **completely**, with the motivating case:
*"give me all the job descriptions across all the PDFs."*

## Depends on
POC-1 (a chosen parser producing clean markdown + heading hierarchy).

## Core thesis
"Give me **all** X" is an **exhaustive / structured** intent. Pure vector
similarity is recall-limited — it returns *some* and silently misses others. So
sections must be **typed first-class rows**, and completeness queries become a
**metadata filter**, not a similarity guess. Vector search is reserved for fuzzy
"find me something about…" queries.

## Pipeline

### 1. Structure-aware chunking
- Split markdown on heading boundaries (using POC-1's heading hierarchy).
- Each chunk = one section, with metadata:
  ```python
  @dataclass
  class Section:
      doc_id: str
      section_title: str
      hierarchy_path: list[str]   # e.g. ["Chapter 2", "Roles", "Backend Engineer"]
      page_range: tuple[int, int]
      markdown: str
      section_type: str | None    # filled in step 2
      embedding: list[float] | None
  ```
- Oversized sections sub-chunked for embedding while keeping the parent section id.

### 2. Section classification / tagging (at ingest)
- LLM classifies each section into a taxonomy, e.g.
  `job_description | compensation | requirements | company_overview | benefits | other`.
- Taxonomy is configurable; start small, expand from observed samples.
- Store `section_type` as queryable metadata. Keep the model's confidence.

### 3. Retrieval — three legs
- **Metadata filter** — `section_type = X` → guarantees completeness for "all X".
- **Vector similarity** — semantic "about Y" queries.
- **Keyword / BM25** — exact terms, names, codes.

### 4. Query routing (agentic)
- An LLM maps the user's question to a strategy:
  - "all job descriptions" → filter `section_type=job_description`, return every match.
  - "what's the salary range for backend roles" → filter + vector + synthesize.
  - "summarize the benefits" → vector + synthesize.
- Router returns the retrieved sections + a synthesized answer **with citations**
  (doc_id + page_range + section_title).

## Storage (POC = simple, port later)
- POC: SQLite/Parquet for sections + a local vector store (LanceDB/Chroma).
- Production (Frappe): `Source Document`, `Parsed Page`, `Document Section`
  DocTypes; vectors in pgvector or an external store with Frappe as system of
  record. "All X" is then a plain Frappe query/report.

## Evaluation
- Build a small gold set: for the sample PDFs, manually list every job-description
  section (and a couple other types).
- Metrics: **recall** (did we return *all* of them? — the whole point),
  precision, and citation correctness.
- Compare: metadata-filter approach vs naive top-k vector RAG → demonstrate the
  recall gap on "all X" queries.

## Success criteria
- "Give me all job descriptions" returns **100%** of gold sections across docs,
  with correct citations.
- Naive vector RAG measurably under-recalls on the same query (justifies the design).
- Routing picks the right strategy on a handful of representative questions.

## Out of scope (this POC)
- Chat UI / multi-turn memory (later).
- Frappe DocType implementation (later).
- Access control / multi-tenant.
