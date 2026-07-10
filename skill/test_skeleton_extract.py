#!/usr/bin/env python3
"""Synthetic-only tests for deterministic skeleton extraction."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry  # noqa: E402
import skeleton_extract as se  # noqa: E402


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _row(identifier, body, *, split="train", medium="threads", level="ok"):
    return {
        "schema_version": registry.SCHEMA_VERSION,
        "proof_class": registry.PROOF_CLASS,
        "id": identifier,
        "ref": identifier,
        "medium": medium,
        "genre": None,
        "grade": {"src": "auto", "score": 0.5},
        "substance": {"level": level, "reasons": []},
        "body": body,
        "chars": len(body),
        "date": "2026-01-01",
        "topic_keys": [],
        "skeleton": None,
        "split": split,
    }


class CoreExtractionTests(unittest.TestCase):
    def test_schema_slots_lists_endings_and_ratios(self):
        text = (
            "첫 문장은 분명합니다.\n\n"
            "1) 첫 항목입니다.\n2) 둘째 항목입니다.\n\n"
            "하지만 방향을 다시 봐요.\n\n"
            "마지막 선택일까?"
        )
        skeleton = se.extract_skeleton(text)

        self.assertEqual(
            set(skeleton),
            {
                "schema_version", "proof_class", "blocks", "paragraphs",
                "single_sentence_para_ratio", "list_format", "provenance",
            },
        )
        self.assertEqual(skeleton["schema_version"], "skeleton-v1")
        self.assertEqual(skeleton["proof_class"], "deterministic")
        self.assertEqual(skeleton["provenance"], "결정골격=py")
        self.assertEqual(skeleton["paragraphs"], 4)
        self.assertEqual(skeleton["single_sentence_para_ratio"], 0.75)
        self.assertEqual(skeleton["list_format"], "N)")
        self.assertEqual(
            [block["slot"] for block in skeleton["blocks"]],
            ["도입", "전개", "전환", "마무리"],
        )
        self.assertEqual(
            [block["ending"] for block in skeleton["blocks"]],
            ["합니다", "합니다", "해요", "질문"],
        )
        listed = skeleton["blocks"][1]
        self.assertTrue(listed["has_list"])
        self.assertEqual(listed["list_format"], "N)")
        self.assertEqual(listed["lines"], 2)
        self.assertEqual([block["idx"] for block in skeleton["blocks"]], [0, 1, 2, 3])
        self.assertEqual(
            set(skeleton["blocks"][0]),
            {
                "idx", "slot", "subtype", "lines", "chars", "has_list",
                "list_format", "ending", "fn",
            },
        )
        self.assertTrue(all(block["subtype"] is None and block["fn"] is None for block in skeleton["blocks"]))

    def test_frontmatter_is_ignored_and_one_block_prefers_intro(self):
        skeleton = se.extract_skeleton("---\ntitle: 메타\n---\n본문 한 줄이다.")
        self.assertEqual(skeleton["paragraphs"], 1)
        self.assertEqual(skeleton["blocks"][0]["slot"], "도입")
        self.assertEqual(skeleton["blocks"][0]["ending"], "평어다")

    def test_remaining_ending_categories(self):
        self.assertEqual(se.classify_block_ending("기록했음"), "음슴")
        self.assertEqual(se.classify_block_ending("핵심 요약"), "명사종결")
        self.assertEqual(se.classify_block_ending("끝!"), "기타")


class CliAndRegistryTests(unittest.TestCase):
    def test_standalone_cli_requires_and_writes_explicit_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "draft.md"
            output = root / "result.json"
            source.write_text("첫 문장입니다.\n\n마지막 문장입니다.", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = se.main(["--input", str(source), "--output", str(output)])

            self.assertEqual(code, 0, stderr.getvalue())
            status = json.loads(stdout.getvalue())
            self.assertEqual(status["output"], str(output))
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(artifact["schema_version"], "skeleton-v1")

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                missing_code = se.main(["--input", str(source)])
            self.assertEqual(missing_code, 1)
            self.assertIn("explicit --output", stderr.getvalue())

    def test_registry_item_uses_canonical_path_and_seals_final(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "personas"
            registry_path = data_root / "시험" / "exemplars.jsonl"
            _write_jsonl(
                registry_path,
                [
                    _row("train-id", "훈련 문장입니다.", split="train"),
                    _row("final-id", "봉인 문장입니다.", split="final"),
                ],
            )
            status = se.extract_registry_item(data_root, "시험", "train-id")
            expected = data_root / "시험" / "skeletons" / "train-id.json"
            self.assertEqual(Path(status["output"]), expected)
            self.assertTrue(expected.is_file())
            with self.assertRaisesRegex(se.SkeletonError, "final split is sealed"):
                se.extract_registry_item(data_root, "시험", "final-id")
            unsealed = se.extract_registry_item(
                data_root, "시험", "final-id", unseal_final=True
            )
            self.assertTrue(Path(unsealed["output"]).is_file())

    def test_batch_filters_medium_split_and_substance_then_links_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "personas"
            registry_path = data_root / "시험" / "exemplars.jsonl"
            rows = [
                _row("wanted", "첫 문장입니다.\n\n끝 문장입니다."),
                _row("low", "짧은 반응", level="low"),
                _row("dev", "개선 문장입니다.", split="dev"),
                _row("long", "긴 글 문장입니다.", medium="longform"),
            ]
            _write_jsonl(registry_path, rows)
            result = se.batch_extract(
                data_root, "시험", split="train", medium="threads"
            )

            self.assertEqual(result["selected"], 2)
            self.assertEqual(result["extracted"], 1)
            self.assertEqual(result["failed"], 0)
            self.assertEqual(result["skipped_low_substance"], 1)
            self.assertEqual(result["sample_id"], "wanted")
            stored = {row["id"]: row for row in registry.load_registry(registry_path)}
            self.assertEqual(stored["wanted"]["skeleton"], "skeletons/wanted.json")
            self.assertIsNone(stored["low"]["skeleton"])
            self.assertIsNone(stored["dev"]["skeleton"])
            self.assertIsNone(stored["long"]["skeleton"])
            self.assertTrue((data_root / "시험" / "skeletons" / "wanted.json").is_file())
            with self.assertRaisesRegex(se.SkeletonError, "final split is sealed"):
                se.batch_extract(data_root, "시험", split="final")

    def test_batch_rejects_registry_id_path_traversal_per_item(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "personas"
            registry_path = data_root / "시험" / "exemplars.jsonl"
            _write_jsonl(
                registry_path,
                [_row("../../../escape", "경계를 벗어나면 안 됩니다.")],
            )

            result = se.batch_extract(data_root, "시험")

            self.assertEqual((result["extracted"], result["failed"]), (0, 1))
            self.assertIn("one path component", result["failures"][0]["reason"])
            self.assertFalse((Path(directory) / "escape.json").exists())


class LabelMergeTests(unittest.TestCase):
    def test_item_level_merge_accepts_valid_and_rejects_bad_items(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "personas"
            persona = data_root / "시험"
            skeleton_dir = persona / "skeletons"
            skeleton_dir.mkdir(parents=True)
            base = se.extract_skeleton("첫 문장입니다.\n\n마지막 문장입니다.")
            se._write_json(base, skeleton_dir / "valid.json")
            se._write_json(base, skeleton_dir / "bad-count.json")
            se._write_json(base, skeleton_dir / "bad-subtype.json")
            _write_jsonl(
                persona / "exemplars.jsonl",
                [
                    _row("valid", "첫 문장입니다.\n\n마지막 문장입니다."),
                    _row("bad-count", "첫 문장입니다.\n\n마지막 문장입니다."),
                    _row("bad-subtype", "첫 문장입니다.\n\n마지막 문장입니다."),
                ],
            )
            (persona / "subtypes.json").write_text(
                json.dumps({"subtypes": ["OP-A", "CL-B"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            labels = Path(directory) / "labels.jsonl"
            _write_jsonl(
                labels,
                [
                    {
                        "id": "valid",
                        "blocks": [
                            {"idx": 0, "subtype": "OP-A", "fn": "문을 연다"},
                            {"idx": 1, "subtype": "CL-B", "fn": "문을 닫는다"},
                        ],
                    },
                    {
                        "id": "bad-count",
                        "blocks": [{"idx": 0, "subtype": "OP-A", "fn": None}],
                    },
                    {
                        "id": "bad-subtype",
                        "blocks": [
                            {"idx": 0, "subtype": "UNKNOWN", "fn": None},
                            {"idx": 1, "subtype": "CL-B", "fn": None},
                        ],
                    },
                ],
            )
            report_path = Path(directory) / "merge-report.json"
            report = se.merge_labels(data_root, "시험", labels, report_path)

            self.assertEqual(report["accepted"], 1)
            self.assertEqual(report["rejected"], 2)
            self.assertEqual(len(report["rejects"]), 2)
            self.assertTrue(report_path.is_file())
            merged = json.loads((skeleton_dir / "valid.json").read_text(encoding="utf-8"))
            self.assertEqual(merged["provenance"], "결정골격=py|기능라벨=llm")
            self.assertEqual(merged["blocks"][0]["subtype"], "OP-A")
            unchanged = json.loads(
                (skeleton_dir / "bad-count.json").read_text(encoding="utf-8")
            )
            self.assertEqual(unchanged["provenance"], "결정골격=py")

    def test_missing_whitelist_allows_null_unclassified_label(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "personas"
            skeleton = data_root / "시험" / "skeletons" / "one.json"
            se._write_json(se.extract_skeleton("한 문장입니다."), skeleton)
            _write_jsonl(
                data_root / "시험" / "exemplars.jsonl",
                [_row("one", "한 문장입니다.")],
            )
            labels = Path(directory) / "labels.jsonl"
            _write_jsonl(
                labels,
                [{"id": "one", "blocks": [{"idx": 0, "subtype": None, "fn": None}]}],
            )
            report = se.merge_labels(data_root, "시험", labels)
            self.assertEqual((report["accepted"], report["rejected"]), (1, 0))

    def test_boolean_block_index_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "personas"
            skeleton = data_root / "시험" / "skeletons" / "one.json"
            se._write_json(se.extract_skeleton("한 문장입니다."), skeleton)
            _write_jsonl(
                data_root / "시험" / "exemplars.jsonl",
                [_row("one", "한 문장입니다.")],
            )
            labels = Path(directory) / "labels.jsonl"
            _write_jsonl(
                labels,
                [{"id": "one", "blocks": [{"idx": True, "subtype": None, "fn": None}]}],
            )

            report = se.merge_labels(data_root, "시험", labels)

            self.assertEqual((report["accepted"], report["rejected"]), (0, 1))
            self.assertIn("invalid or duplicate", report["rejects"][0]["reason"])

    def test_final_label_merge_stays_sealed_without_explicit_unseal(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "personas"
            skeleton_path = data_root / "시험" / "skeletons" / "sealed.json"
            original = se.extract_skeleton("봉인 문장입니다.")
            se._write_json(original, skeleton_path)
            _write_jsonl(
                data_root / "시험" / "exemplars.jsonl",
                [_row("sealed", "봉인 문장입니다.", split="final")],
            )
            labels = Path(directory) / "labels.jsonl"
            _write_jsonl(
                labels,
                [{"id": "sealed", "blocks": [{"idx": 0, "subtype": None, "fn": "결론"}]}],
            )

            sealed = se.merge_labels(data_root, "시험", labels)
            self.assertEqual((sealed["accepted"], sealed["rejected"]), (0, 1))
            self.assertIn("final split is sealed", sealed["rejects"][0]["reason"])
            self.assertEqual(
                json.loads(skeleton_path.read_text(encoding="utf-8"))["provenance"],
                "결정골격=py",
            )

            unsealed = se.merge_labels(
                data_root, "시험", labels, unseal_final=True
            )
            self.assertEqual((unsealed["accepted"], unsealed["rejected"]), (1, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
