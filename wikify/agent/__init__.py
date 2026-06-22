"""Wikify AI agent — a chat assistant that reads and (later) edits the conversion.

Architecture is adapted from Frappe Builder's `ai-session` branch and deliberately
simplified: no canvas, no artifact model. Tools run server-side and return text; a few
enqueue existing pipeline jobs. See `specs/0.2/02-ai-agent.md`.

Slice 12 ships the walking skeleton: global scope, one read tool (`read_tree`),
streaming over realtime, persisted messages. Slices 13-14 thicken it (attachment
context, then write/re-parse tools).
"""
