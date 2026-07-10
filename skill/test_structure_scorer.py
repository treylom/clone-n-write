#!/usr/bin/env python3
"""Synthetic-only tests for the non-gating structure scorer."""

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skeleton_extract  # noqa: E402
import structure_profiler  # noqa: E402
import structure_scorer as ss  # noqa: E402


BASE_BODY = "첫 문장은 구조를 엽니다.\n\n1) 근거를 놓습니다.\n2) 사례를 붙입니다.\n\n마지막 문장은 닫습니다."


def _pack(persona="시험", medium="threads"):
    records = [
        {"body": BASE_BODY, "genre": "정보", "medium": medium}
        for _ in range(10)
    ]
    return structure_profiler.build_profile(records, medium=medium, persona=persona)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture(directory):
    root = Path(directory)
    data_root = root / "personas"
    pack_path = data_root / "시험" / "packs" / "structure-threads.json"
    _write_json(pack_path, _pack())
    draft = root / "draft.md"
    draft.write_text(BASE_BODY, encoding="utf-8")
    return root, data_root, draft


class BandComparisonTests(unittest.TestCase):
    def test_all_structural_leaves_include_symbols_but_no_ending_style(self):
        result = ss.compare_bands(BASE_BODY, _pack(), genre="정보")
        keys = set(result["in_band"])
        self.assertIn("paragraphs", keys)
        self.assertIn("sentence_len.cv", keys)
        self.assertIn("symbol_per10k.arrow", keys)
        self.assertIn("bold_rate", keys)
        self.assertIn("list_format", keys)
        self.assertFalse(any("ending" in key or "formal" in key or "polite" in key for key in keys))
        self.assertTrue(all(isinstance(value, bool) for value in result["in_band"].values()))
        self.assertEqual(result["in_band_ratio"], 1.0)
        feature_lines = [line for line in result["diagnostics"] if line.startswith("[대역")]
        self.assertTrue(feature_lines)
        self.assertTrue(all("왜:" in line and "코칭:" in line for line in feature_lines))

    def test_out_of_band_draft_has_positive_l2_and_coaching(self):
        body = "아주 짧다."
        result = ss.compare_bands(body, _pack())
        self.assertLess(result["in_band_ratio"], 1.0)
        self.assertGreater(result["l2_distance"], 0.0)
        self.assertTrue(any("[대역 밖" in line for line in result["diagnostics"]))

    def test_frontmatter_does_not_enter_measured_body(self):
        with tempfile.TemporaryDirectory() as directory:
            _root, data_root, draft = _fixture(directory)
            draft.write_text(
                "---\ntitle: 이 메타는 매우 길지만 구조에 포함하지 않는다\n---\n" + BASE_BODY,
                encoding="utf-8",
            )
            report, _diagnostics, _output = ss.score_file(
                draft, "시험", "threads", data_root
            )
            self.assertEqual(report["metrics"]["features"]["chars"], len(BASE_BODY))


class SkeletonAdherenceTests(unittest.TestCase):
    def test_identical_body_is_perfect_and_reports_all_components(self):
        skeleton = skeleton_extract.extract_skeleton(BASE_BODY)
        score, details = ss.skeleton_adherence(BASE_BODY, skeleton)
        self.assertEqual(score, 1.0)
        self.assertEqual(details["slot_score"], 1.0)
        self.assertEqual(details["block_count_delta"], 0)
        self.assertEqual(details["block_length_score"], 1.0)
        self.assertTrue(details["list_format_match"])

    def test_changed_blocks_and_list_format_reduce_adherence(self):
        skeleton = skeleton_extract.extract_skeleton(BASE_BODY)
        changed = "도입만 아주 짧게 남깁니다.\n\n하지만 별도 전환을 둡니다."
        score, details = ss.skeleton_adherence(changed, skeleton)
        self.assertGreaterEqual(score, 0.0)
        self.assertLess(score, 1.0)
        self.assertEqual(details["block_count_delta"], -1)
        self.assertFalse(details["list_format_match"])


class ManifestAndCliTests(unittest.TestCase):
    def test_manifest_matches_actual_skeleton_and_outline_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, data_root, draft = _fixture(directory)
            skeleton_path = data_root / "시험" / "skeletons" / "anchor.json"
            skeleton_extract._write_json(
                skeleton_extract.extract_skeleton(BASE_BODY), skeleton_path
            )
            outline = root / "outline.md"
            outline.write_text("승인된 개요 원자", encoding="utf-8")
            manifest_path = root / "manifest.json"
            manifest = {
                "skeleton_id": "anchor",
                "skeleton_sha256": hashlib.sha256(skeleton_path.read_bytes()).hexdigest(),
                "outline_sha256": hashlib.sha256(outline.read_bytes()).hexdigest(),
                "outline_path": "outline.md",
            }
            _write_json(manifest_path, manifest)

            report, diagnostics, output = ss.score_file(
                draft,
                "시험",
                "threads",
                data_root,
                skeleton_spec="anchor",
                manifest_path=manifest_path,
            )
            self.assertTrue(report["manifest_ok"])
            self.assertEqual(report["adherence"], 1.0)
            self.assertTrue(any("MANIFEST_OK" in line for line in diagnostics))
            self.assertEqual(output, Path(str(draft) + ".structure.json"))
            artifact = json.loads(output.read_text(encoding="utf-8"))
            for key in (
                "schema_version", "proof_class", "in_band", "in_band_ratio",
                "adherence", "manifest_ok", "verdict",
            ):
                self.assertIn(key, artifact)
            self.assertEqual(artifact["verdict"], "diagnostic")

    def test_manifest_mismatch_is_explicit_and_no_outline_evidence_is_not_green(self):
        with tempfile.TemporaryDirectory() as directory:
            root, data_root, draft = _fixture(directory)
            skeleton_path = data_root / "시험" / "skeletons" / "anchor.json"
            skeleton_extract._write_json(
                skeleton_extract.extract_skeleton(BASE_BODY), skeleton_path
            )
            manifest_path = root / "manifest.json"
            _write_json(
                manifest_path,
                {
                    "skeleton_id": "anchor",
                    "skeleton_sha256": "0" * 64,
                    "outline_sha256": "1" * 64,
                },
            )
            report, diagnostics, _output = ss.score_file(
                draft,
                "시험",
                "threads",
                data_root,
                skeleton_spec="anchor",
                manifest_path=manifest_path,
            )
            self.assertFalse(report["manifest_ok"])
            joined = "\n".join(diagnostics)
            self.assertIn("MANIFEST_MISMATCH", joined)
            self.assertIn("no verifiable outline", joined)

    def test_cli_prints_korean_diagnostics_writes_literal_sidecar_and_always_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            _root, data_root, draft = _fixture(directory)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = ss.main([
                    "--input", str(draft),
                    "--persona", "시험",
                    "--medium", "threads",
                    "--data-root", str(data_root),
                ])
            self.assertEqual(code, 0)
            output = Path(str(draft) + ".structure.json")
            self.assertTrue(output.is_file())
            self.assertIn("대역", stdout.getvalue())
            self.assertIn("왜:", stdout.getvalue())
            self.assertIn("코칭:", stdout.getvalue())

            missing = Path(directory) / "missing.md"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                error_code = ss.main([
                    "--input", str(missing),
                    "--persona", "시험",
                    "--medium", "threads",
                    "--data-root", str(data_root),
                ])
            self.assertEqual(error_code, 0)
            self.assertIn("구조 진단 오류", stdout.getvalue())

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                parse_code = ss.main([])
            self.assertEqual(parse_code, 0)
            self.assertIn("required", stdout.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
