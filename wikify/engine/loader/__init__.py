"""Markdown post-processing — ported from the POC `loader/` package.

Slice 3 surface: `cleanup` (cross-page boilerplate strip — wired in at sectionize,
Slice 4), `cleanup_llm` (cheap text-model restructure), `table_stitch` (merge tables
pymupdf split across a page boundary). Logic is unchanged from the POC; the LLM calls
go through `engine.llm` and model ids come from `engine.settings`.
"""
