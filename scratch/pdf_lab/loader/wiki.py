"""Generate a wiki from an ingested document (future-phase POC).

Two passes (see wiki-generation-phase-notes):
  1. Derive the page tree — each top-level (L1) section becomes a wiki page with a
     stable slug; descendants render inline. This gives every page an id BEFORE
     linking, so references can resolve.
  2. Rewrite internal page-number references ("refer Page No. 3", "see page 12")
     into links to the wiki page that covers that PDF page. External book citations
     ("Williams Obstetrics page 820") are left as text.

The same link rewrite runs over all content including tables.
"""

from __future__ import annotations

import re

from loader import graph

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Optional see/refer cue, the word page/pg/p (with optional "no"), then the number.
_PAGEREF_RE = re.compile(
    r"((?:see|refer(?:\s+to)?)\s+)?(page\s*no\.?|page|pg\.?|p\.)\s*(\d{1,4})\b", re.I
)


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")[:60] or "page"


def _depth(section) -> int:
    """Heading depth from the stored hierarchy_path ('A > B > C' -> 3)."""
    hp = section["hierarchy_path"] or section["title"] or ""
    return max(1, len([p for p in hp.split(" > ") if p]))


def build_wiki(doc_id: str) -> dict:
    doc = graph.get_document(doc_id)
    page_count = (doc or {}).get("page_count") or 10**9
    sections = graph.get_sections(doc_id)

    # --- Pass 1: group sections under their L1 ancestor → one wiki page each ---
    groups: dict[str, list] = {}
    order: list[str] = []
    for s in sections:
        l1 = (s["hierarchy_path"] or s["title"] or "Untitled").split(" > ")[0]
        if l1 not in groups:
            groups[l1] = []
            order.append(l1)
        groups[l1].append(s)

    pages = []
    used: set[str] = set()
    for i, l1 in enumerate(order):
        g = groups[l1]
        slug = base = slugify(l1)
        k = 2
        while slug in used:
            slug, k = f"{base}-{k}", k + 1
        used.add(slug)
        pages.append({
            "slug": slug, "title": l1, "ordinal": i, "sections": g,
            "page_start": min(s["page_start"] for s in g),
            "page_end": max(s["page_end"] for s in g),
        })

    def slug_for_page(n: int):
        """Smallest wiki page whose PDF-page range contains n."""
        best = None
        for p in pages:
            if p["page_start"] <= n <= p["page_end"]:
                span = p["page_end"] - p["page_start"]
                if best is None or span < best[1]:
                    best = (p["slug"], span)
        return best[0] if best else None

    # --- Pass 2: render markdown + resolve internal references ---
    graph.clear_wiki(doc_id)
    total_links = 0
    for p in pages:
        parts = []
        for s in p["sections"]:
            rel = min(6, _depth(s))
            parts.append("#" * rel + " " + s["title"])
            if (s["markdown"] or "").strip():
                parts.append(s["markdown"])
        md = "\n\n".join(parts)

        links = [0]

        def repl(m):
            cue, kind, num = m.group(1), m.group(2), int(m.group(3))
            internal = bool(cue) or "no" in kind.lower()  # cross-ref cue or "Page No." form
            if internal and 1 <= num <= page_count:
                tgt = slug_for_page(num)
                if tgt and tgt != p["slug"]:
                    links[0] += 1
                    return f"[{m.group(0)}](/doc/{doc_id}/wiki/{tgt})"
            return m.group(0)

        md = _PAGEREF_RE.sub(repl, md)
        total_links += links[0]
        graph.add_wiki_page(doc_id, {
            "slug": p["slug"], "title": p["title"], "ordinal": p["ordinal"],
            "page_start": p["page_start"], "page_end": p["page_end"],
            "markdown": md, "ref_links": links[0],
        })

    return {"pages": len(pages), "internal_links": total_links}
