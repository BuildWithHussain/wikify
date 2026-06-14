"""PDF Lab — Flask POC for the parse + load pipeline.

Run:  flask --app app run --debug
"""

from __future__ import annotations

import datetime as dt
import html
import re
import uuid
from pathlib import Path

import markdown as md_lib
from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

import config
from loader import graph
from parsers.registry import available_parsers
from pipeline import process_document

app = Flask(__name__)
graph.init_db()


_MERMAID_RE = re.compile(r'<pre><code class="language-mermaid">(.*?)</code></pre>', re.DOTALL)


def _render_md(text: str) -> str:
    out = md_lib.markdown(text or "", extensions=["tables", "fenced_code", "sane_lists"])
    # Turn ```mermaid blocks into elements mermaid.js renders (needs unescaped source).
    return _MERMAID_RE.sub(lambda m: f'<pre class="mermaid">{html.unescape(m.group(1))}</pre>', out)


@app.route("/")
def index():
    return render_template(
        "index.html",
        documents=graph.list_documents(),
        parsers=available_parsers(),
        type_counts=graph.section_type_counts(),
        section_types=config.SECTION_TYPES,
        has_key=config.has_openrouter(),
    )


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("pdf")
    if not file or not file.filename:
        abort(400, "No file uploaded")
    parser_name = request.form.get("parser", "pymupdf4llm")
    use_judge = request.form.get("use_judge") == "on"
    classify = request.form.get("classify") == "on"

    doc_id = uuid.uuid4().hex[:12]
    filename = secure_filename(file.filename)
    pdf_path = config.UPLOADS_DIR / f"{doc_id}_{filename}"
    file.save(pdf_path)

    from pdf_utils import page_count

    graph.create_document(
        doc_id, filename, dt.datetime.now().isoformat(timespec="seconds"),
        page_count(pdf_path), parser_name, "processing", source_path=str(pdf_path),
    )
    try:
        process_document(doc_id, str(pdf_path), parser_name, use_judge=use_judge, classify=classify)
    except Exception as e:
        graph.finish_document(doc_id, f"error: {e}", 0.0)
    return redirect(url_for("document", doc_id=doc_id))


@app.route("/doc/<doc_id>")
def document(doc_id):
    doc = graph.get_document(doc_id)
    if not doc:
        abort(404)
    # Default to the Flagged tab (the pages routed for review); ?tab=all shows everything.
    tab = request.args.get("tab", "flagged")
    scores = graph.get_page_scores(doc_id)
    escalations = graph.get_escalations(doc_id)

    def canonical(s):
        """Canonical for this page: the remediation if it was adopted, else baseline."""
        e = escalations.get(s["page_no"])
        if e and e["adopted"]:
            return e["composite"], e["verdict"]
        return s["composite"], s["verdict"]

    flagged_count = sum(1 for s in scores if canonical(s)[1] != "pass")

    if tab == "all":
        visible = scores
    elif tab == "escalated":
        visible = [s for s in scores if s["page_no"] in escalations]
    else:
        visible = [s for s in scores if canonical(s)[1] != "pass"]
    page_dir = config.PAGES_DIR / doc_id
    pages = []
    for s in visible:
        p = s["page_no"]
        base_md = page_dir / f"page-{p:04d}.md"
        base_text = base_md.read_text(encoding="utf-8") if base_md.exists() else ""
        canon_composite, canon_verdict = canonical(s)
        page = {
            "score": s,
            "canonical": {"composite": canon_composite, "verdict": canon_verdict},
            "image_url": url_for("page_asset", doc_id=doc_id, name=f"page-{p:04d}.png"),
            "html": _render_md(base_text),
            "md": base_text,
            "escalation": None,
        }
        esc = escalations.get(p)
        if esc:
            esc_md = page_dir / f"page-{p:04d}.{esc['parser']}.md"
            esc_text = esc_md.read_text(encoding="utf-8") if esc_md.exists() else ""
            page["escalation"] = {
                "score": esc,
                "html": _render_md(esc_text),
                "md": esc_text,
                "delta": round(esc["composite"] - s["composite"], 3),
                "adopted": bool(esc["adopted"]),
            }
        pages.append(page)

    return render_template(
        "document.html", doc=doc, pages=pages, tab=tab,
        flagged_count=flagged_count, total_count=len(scores),
        escalated_count=len(escalations), can_escalate=config.has_openrouter(),
    )


@app.route("/doc/<doc_id>/escalate", methods=["POST"])
def escalate(doc_id):
    doc = graph.get_document(doc_id)
    if not doc:
        abort(404)
    src = doc.get("source_path")
    if not src or not Path(src).exists():
        abort(400, "Source PDF not available for re-parsing")
    from pipeline import remediate_document

    try:
        # Router picks cheap text-cleanup or VLM re-parse per flagged page.
        remediate_document(doc_id, src)
    except Exception as e:
        abort(500, f"Remediation failed: {e}")
    return redirect(url_for("document", doc_id=doc_id, tab="escalated"))


@app.route("/doc/<doc_id>/sections")
def doc_sections(doc_id):
    doc = graph.get_document(doc_id)
    if not doc:
        abort(404)
    stype = request.args.get("type") or None
    sections = graph.get_sections(doc_id, stype)
    for s in sections:
        s["html"] = _render_md(s["markdown"])
    return render_template(
        "sections.html", doc=doc, sections=sections, active_type=stype,
        section_types=config.SECTION_TYPES, scope="document",
    )


@app.route("/sections")
def all_sections():
    stype = request.args.get("type") or None
    sections = graph.sections_by_type(stype) if stype else []
    for s in sections:
        s["html"] = _render_md(s["markdown"])
    return render_template(
        "sections.html", doc=None, sections=sections, active_type=stype,
        section_types=config.SECTION_TYPES, scope="all",
        type_counts=graph.section_type_counts(),
    )


@app.route("/doc/<doc_id>/wiki/build", methods=["POST"])
def wiki_build(doc_id):
    if not graph.get_document(doc_id):
        abort(404)
    from loader.wiki import build_wiki

    build_wiki(doc_id)
    return redirect(url_for("wiki_index", doc_id=doc_id))


@app.route("/doc/<doc_id>/wiki")
def wiki_index(doc_id):
    doc = graph.get_document(doc_id)
    if not doc:
        abort(404)
    return render_template("wiki_index.html", doc=doc, pages=graph.list_wiki_pages(doc_id))


@app.route("/doc/<doc_id>/wiki/<slug>")
def wiki_page(doc_id, slug):
    doc = graph.get_document(doc_id)
    if not doc:
        abort(404)
    page = graph.get_wiki_page(doc_id, slug)
    if not page:
        abort(404)
    page["html"] = _render_md(page["markdown"])
    return render_template(
        "wiki_page.html", doc=doc, page=page, pages=graph.list_wiki_pages(doc_id))


@app.route("/report")
def report():
    import json

    path = config.STORAGE_DIR / "benchmark.json"
    data = json.loads(path.read_text()) if path.exists() else None
    return render_template("report.html", data=data)


@app.route("/pages/<doc_id>/<name>")
def page_asset(doc_id, name):
    return send_from_directory(config.PAGES_DIR / doc_id, Path(name).name)


if __name__ == "__main__":
    app.run(debug=True)
