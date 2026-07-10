#!/usr/bin/env python3
"""Focused tests for the deterministic structure profiler.

All corpus examples are inline synthetic Korean; no persona corpus is imported.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import structure_profiler as sp  # noqa: E402


def _row(body, medium="스레드", genre="정보", level="ok"):
    return {
        "body": body,
        "medium": medium,
        "genre": genre,
        "substance": {"level": level},
    }


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class QuantileTests(unittest.TestCase):
    def test_exact_type7_quantiles_and_band(self):
        summary = sp.summarize([0, 10, 20, 30, 40])
        self.assertEqual(summary["mean"], 20.0)
        self.assertEqual(summary["p10"], 4.0)
        self.assertEqual(summary["p25"], 10.0)
        self.assertEqual(summary["p50"], 20.0)
        self.assertEqual(summary["p75"], 30.0)
        self.assertEqual(summary["p90"], 36.0)
        self.assertEqual(summary["band"], [4.0, 36.0])


class LoadingTests(unittest.TestCase):
    def test_medium_substance_filters_and_body_precedence(self):
        rows = [
            {
                **_row("정본 문장이다."),
                "text": "이 문장은 선택되면 안 된다.",
            },
            _row("다른 매체 문장이다.", medium="블로그"),
            _row("알맹이가 부족한 문장이다.", level="thin"),
            {
                "body": "조건이 빠진 문장이다.",
                "medium": "스레드",
                "genre": "정보",
            },
            {
                "body": "  ",
                "text": "이전 형식의 대체 본문이다.",
                "medium": "스레드",
                "genre": "사색",
                "substance": {"level": "ok"},
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exemplars.jsonl"
            _write_jsonl(path, rows)
            selected = sp.load_exemplars(path, "스레드")

        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0]["body"], "정본 문장이다.")
        self.assertEqual(selected[1]["body"], "이전 형식의 대체 본문이다.")

    def test_empty_selection_refuses_unmeasured_pack(self):
        with self.assertRaises(sp.ProfileError):
            sp.build_profile([], medium="스레드", persona="시험")


class FeatureTests(unittest.TestCase):
    def test_korean_endings_and_newline_heuristic(self):
        punctuated = (
            "간다. 옵니다. 좋아요. 기록했음. 정리함. "
            "맞을까? 그렇죠. 끝!"
        )
        self.assertEqual(len(sp.split_sentences(punctuated)), 8)
        self.assertEqual(sp.split_sentences("표현 하나\n표현 둘"), ["표현 하나", "표현 둘"])

    def test_paragraph_sentence_and_blank_line_metrics(self):
        features = sp.document_features("하나다.\n둘이다.\n\n셋이다.")
        self.assertEqual(features["lines"], 4)
        self.assertEqual(features["paragraphs"], 2)
        self.assertEqual(features["blank_line_count"], 1)
        self.assertEqual(features["sentences_per_paragraph"], 1.5)
        self.assertEqual(features["single_sentence_para_ratio"], 0.5)

    def test_list_usage_and_categorical_format(self):
        measured = sp.document_metrics("1)하나\n2) 둘\n일반 문장")
        self.assertEqual(measured["list_format"], "N)")
        self.assertAlmostEqual(measured["features"]["list_usage"], 2 / 3)

        tied = sp.document_metrics("1)하나\n2.둘\n-셋")
        self.assertEqual(tied["list_format"], "N)", "동률 우선순위는 N) → N. → -")

        protected = sp.document_metrics("3.14는 원주율이다.\n---\n-3은 음수다.")
        self.assertEqual(protected["list_format"], "none")

    def test_symbol_and_bold_rates_are_per_10k_chars(self):
        body = "→ … '말' ㅋㅋ ㅎㅎ (괄호) **강조**"
        features = sp.document_features(body)
        unit = 10000.0 / len(body)
        symbols = features["symbol_per10k"]
        self.assertAlmostEqual(symbols["arrow"], unit)
        self.assertAlmostEqual(symbols["ellipsis"], unit)
        self.assertAlmostEqual(symbols["single_quote"], unit * 2)
        self.assertAlmostEqual(symbols["kk"], unit)
        self.assertAlmostEqual(symbols["hh"], unit)
        self.assertAlmostEqual(symbols["parentheses"], unit)
        self.assertAlmostEqual(features["bold_rate"], unit)

    def test_question_opening_and_closing(self):
        body = "\n  첫 줄이다.  \n질문일까?\n마지막 줄\n"
        features = sp.document_features(body)
        self.assertEqual(features["opener_len"], len("첫 줄이다."))
        self.assertEqual(features["closer_len"], len("마지막 줄"))
        self.assertEqual(features["question_ratio"], 1 / 3)


class ProfileSchemaTests(unittest.TestCase):
    NUMERIC_ROOTS = (
        "chars",
        "lines",
        "paragraphs",
        "sentences_per_paragraph",
        "single_sentence_para_ratio",
        "list_usage",
        "question_ratio",
        "opener_len",
        "closer_len",
        "bold_rate",
        "blank_line_count",
    )

    def assert_summary(self, value):
        self.assertEqual(set(value), set(sp.SUMMARY_KEYS))
        self.assertEqual(value["band"], [value["p10"], value["p90"]])

    def assert_feature_schema(self, features, n):
        for name in self.NUMERIC_ROOTS:
            self.assert_summary(features[name])
        for name in ("mean", "cv", "p10", "p90"):
            self.assert_summary(features["sentence_len"][name])
        for name in ("arrow", "ellipsis", "single_quote", "kk", "hh", "parentheses"):
            self.assert_summary(features["symbol_per10k"][name])

        categorical = features["list_format"]
        self.assertEqual(set(categorical), {"counts", "distribution", "dominant"})
        self.assertEqual(set(categorical["counts"]), set(sp.LIST_FORMATS))
        self.assertEqual(sum(categorical["counts"].values()), n)
        self.assertAlmostEqual(sum(categorical["distribution"].values()), 1.0)
        self.assertIn(categorical["dominant"], sp.LIST_FORMATS)

    def test_full_schema_and_genre_direction_flags(self):
        records = [
            _row("1) 첫 항목이다.\n둘째 줄이다.", genre="정보")
            for _ in range(10)
        ]
        records.append(_row("한 편의 생각이다.", genre="사색"))
        profile = sp.build_profile(records, medium="스레드", persona="시험")

        self.assertEqual(profile["schema_version"], "struct-v1")
        self.assertEqual(profile["proof_class"], "corpus-measured")
        self.assertEqual(profile["n"], 11)
        self.assert_feature_schema(profile["features"], 11)

        self.assertEqual(set(profile["genres"]), {"정보", "사색"})
        info = profile["genres"]["정보"]
        thought = profile["genres"]["사색"]
        for cell in (info, thought):
            self.assertEqual(cell["schema_version"], "struct-v1")
            self.assertEqual(cell["proof_class"], "corpus-measured")
            self.assert_feature_schema(cell["features"], cell["n"])
        self.assertFalse(info["direction_only"])
        self.assertTrue(thought["direction_only"])

    def test_no_genre_labels_omits_cells(self):
        profile = sp.build_profile(
            [{"body": "라벨 없는 문장이다."}], medium="스레드", persona="시험"
        )
        self.assertNotIn("genres", profile)


class CliTests(unittest.TestCase):
    def test_build_alias_writes_canonical_pack_and_json_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "personas"
            source = root / "시험" / "exemplars.jsonl"
            _write_jsonl(
                source,
                [
                    _row("첫 문장이다.\n둘째 문장이다.", medium="스레드"),
                    _row("제외할 문장이다.", medium="블로그"),
                ],
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = sp.main(
                    [
                        "build",
                        "--persona",
                        "시험",
                        "--medium",
                        "스레드",
                        "--personas-dir",
                        str(root),
                    ]
                )

            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(stderr.getvalue(), "")
            status = json.loads(stdout.getvalue())
            self.assertEqual(status["status"], "ok")
            self.assertEqual(status["schema_version"], "struct-v1")
            self.assertEqual(status["proof_class"], "corpus-measured")
            self.assertEqual(status["n"], 1)

            output = root / "시험" / "packs" / "structure-스레드.json"
            self.assertEqual(Path(status["output"]), output)
            profile = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(profile["persona"], "시험")
            self.assertEqual(profile["medium"], "스레드")
            self.assertEqual(profile["n"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
