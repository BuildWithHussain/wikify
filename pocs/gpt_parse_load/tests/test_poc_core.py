from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

POC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_ROOT))

from pdfpoc.config import load_root_dotenv, openrouter_api_key
from pdfpoc.cli import _cloud_improves_page, _escalation_reasons
from pdfpoc.eval.checks import evaluate_canonical
from pdfpoc.load.loader import load_canonical
from pdfpoc.models import write_json
from pdfpoc.normalize.canonical import canonicalize_raw
from pdfpoc.normalize.markdown_renderer import render_markdown
from pdfpoc.pdf_utils import selected_page_numbers
from pdfpoc.ui.data import build_overview, page_compare, save_page_review


class PocCoreTests(unittest.TestCase):
    def test_dotenv_supports_existing_openrouter_key_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            dotenv = Path(tmp) / ".env"
            dotenv.write_text("OPENROUTER_KEY=test-secret\n", encoding="utf-8")
            old = os.environ.pop("OPENROUTER_KEY", None)
            try:
                load_root_dotenv(dotenv)
                self.assertEqual(openrouter_api_key({}), "test-secret")
            finally:
                if old is not None:
                    os.environ["OPENROUTER_KEY"] = old
                else:
                    os.environ.pop("OPENROUTER_KEY", None)

    def test_canonicalize_builds_sections_from_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "sample.pdf"
            pdf.write_bytes(b"%PDF fake bytes for hashing")
            raw = {
                "provider": "unit",
                "model": "fake",
                "pages": [
                    {
                        "page_number": 1,
                        "width": 612,
                        "height": 792,
                        "rotation": 0,
                        "source_text": "Title\nIntro text.\nDetails\nA B\n1 2",
                        "markdown": "# Title\n\nIntro text.\n\n## Details\n\n| A | B |\n| - | - |\n| 1 | 2 |",
                    }
                ],
            }
            profile = {"name": "unit_profile", "provider": "unit", "model": "fake", "build_sections": True}
            canonical = canonicalize_raw(raw, pdf, profile, run_id="run_unit")
            self.assertEqual(canonical["document"]["filename"], "sample.pdf")
            self.assertEqual(len(canonical["pages"]), 1)
            self.assertEqual(len(canonical["sections"]), 2)
            self.assertEqual(canonical["pages"][0]["metadata"]["source_text"].splitlines()[0], "Title")
            self.assertIn("# Title", render_markdown(canonical))
            self.assertEqual(evaluate_canonical(canonical)["table_count"], 1)
            self.assertEqual(evaluate_canonical(canonical)["text_recall_avg"], 1.0)

    def test_load_canonical_inserts_graph_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "sample.pdf"
            pdf.write_bytes(b"%PDF fake bytes for hashing")
            profile = {"name": "unit_profile", "provider": "unit", "model": "fake", "build_sections": True}
            canonical = canonicalize_raw(
                {
                    "provider": "unit",
                    "model": "fake",
                    "pages": [{"page_number": 1, "markdown": "# Heading\n\nBody"}],
                },
                pdf,
                profile,
                run_id="run_unit",
            )
            db = Path(tmp) / "index.sqlite"
            result = load_canonical(canonical, db)
            self.assertEqual(result["nodes_loaded"], 5)
            with sqlite3.connect(db) as con:
                node_count = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                edge_count = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            self.assertEqual(node_count, 5)
            self.assertGreaterEqual(edge_count, 3)

    def test_ui_data_compares_generated_and_ingested_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF fake bytes for hashing")
            profile = {"name": "unit_profile", "provider": "unit", "model": "fake", "build_sections": True}
            canonical = canonicalize_raw(
                {
                    "provider": "unit",
                    "model": "fake",
                    "pages": [{"page_number": 1, "source_text": "Heading\nBody", "markdown": "# Heading\n\nBody"}],
                },
                pdf,
                profile,
                run_id="run_unit",
            )
            run_dir = root / "runs" / "sample" / "unit_profile" / "run_unit"
            write_json(run_dir / "canonical.json", canonical)
            db = root / "index.sqlite"
            load_canonical(canonical, db)

            overview = build_overview(root / "runs", db)
            self.assertEqual(overview["run_count"], 1)
            comparison = page_compare(
                canonical["document"]["id"],
                1,
                ["run_unit"],
                runs_dir=root / "runs",
                db_path=db,
            )
            self.assertEqual(len(comparison["runs"]), 1)
            page = comparison["runs"][0]["page"]
            self.assertIn("# Heading", page["generated_markdown"])
            self.assertTrue(page["ingested"]["loaded"])
            self.assertIn("# Heading", page["ingested"]["markdown"])

    def test_page_review_annotations_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF fake bytes for hashing")
            profile = {"name": "unit_profile", "provider": "unit", "model": "fake", "build_sections": True}
            canonical = canonicalize_raw(
                {
                    "provider": "unit",
                    "model": "fake",
                    "pages": [{"page_number": 1, "source_text": "Heading\nBody", "markdown": "# Heading\n\nBody"}],
                },
                pdf,
                profile,
                run_id="run_unit",
            )
            run_dir = root / "runs" / "sample" / "unit_profile" / "run_unit"
            write_json(run_dir / "canonical.json", canonical)
            db = root / "index.sqlite"
            load_canonical(canonical, db)

            saved = save_page_review(
                canonical["document"]["id"],
                1,
                {
                    "status": "reviewed",
                    "page_type": "diagram",
                    "winning_parse_run_id": "run_unit",
                    "rejected_run_ids": ["run_bad"],
                    "rejection_reason": "diagram_error",
                    "notes": "Organogram labels preserved.",
                },
                db_path=db,
            )
            self.assertEqual(saved["status"], "reviewed")
            self.assertEqual(saved["page_type"], "diagram")

            comparison = page_compare(
                canonical["document"]["id"],
                1,
                ["run_unit"],
                runs_dir=root / "runs",
                db_path=db,
            )
            self.assertEqual(comparison["review"]["winning_parse_run_id"], "run_unit")
            self.assertEqual(comparison["review"]["rejected_run_ids"], ["run_bad"])
            overview = build_overview(root / "runs", db)
            self.assertEqual(overview["documents"][0]["review"]["total"], 1)

    def test_page_range_parser(self):
        self.assertEqual(selected_page_numbers(10, "1-3,5"), [1, 2, 3, 5])
        self.assertEqual(selected_page_numbers(3, "2-9"), [2, 3])
        self.assertEqual(selected_page_numbers(5, [2, 2, 4]), [2, 4])

    def test_escalation_reasons_flag_low_recall_extra_text_and_table_miss(self):
        scorecard = {
            "page_scores": [
                {"page_number": 1, "text_recall": 0.99, "extra_text_ratio": 0.01, "table_score": 1.0},
                {"page_number": 2, "text_recall": 0.8, "extra_text_ratio": 0.2, "table_score": None},
                {"page_number": 3, "text_recall": 1.0, "extra_text_ratio": 0.0, "table_score": 0.0},
            ]
        }
        reasons = _escalation_reasons(
            scorecard,
            recall_threshold=0.95,
            extra_threshold=0.15,
            escalate_table_miss=True,
        )
        self.assertEqual(sorted(reasons), [2, 3])
        self.assertEqual(len(reasons[2]), 2)
        self.assertEqual(len(reasons[3]), 1)

    def test_cloud_page_must_improve_before_hybrid_replacement(self):
        local = {"text_recall": 1.0, "extra_text_ratio": 0.22, "table_score": None}
        good_cloud = {"text_recall": 0.99, "extra_text_ratio": 0.01, "table_score": None}
        bad_cloud = {"text_recall": 0.43, "extra_text_ratio": 0.02, "table_score": None}
        self.assertTrue(
            _cloud_improves_page(local, good_cloud, recall_threshold=0.95, extra_threshold=0.15)
        )
        self.assertFalse(
            _cloud_improves_page(local, bad_cloud, recall_threshold=0.95, extra_threshold=0.15)
        )


if __name__ == "__main__":
    unittest.main()
