#!/usr/bin/env python3
"""Synthetic-only tests for the v2 exemplar registry."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry as reg  # noqa: E402


LONG_A = "기록을 남기는 일은 생각을 다시 살피게 한다. 작은 차이를 발견하고 다음 선택의 근거를 차분히 정리한다."
LONG_B = "도구를 고를 때는 기능보다 반복 가능한 흐름을 먼저 본다. 실제 작업에 적용한 뒤 결과와 한계를 함께 기록한다."


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _row(identifier, *, split="train", level="ok", score=0.5, topic=None, medium="threads"):
    return {
        "schema_version": reg.SCHEMA_VERSION,
        "proof_class": reg.PROOF_CLASS,
        "id": identifier,
        "ref": identifier,
        "medium": medium,
        "genre": None,
        "grade": {"src": "auto", "score": score},
        "substance": {"level": level, "reasons": []},
        "body": LONG_A,
        "chars": len(LONG_A),
        "date": "2026-01-01",
        "topic_keys": topic or [],
        "skeleton": None,
        "split": split,
    }


class DeterminismTests(unittest.TestCase):
    def test_sha1_split_is_repeatable_and_respects_extremes(self):
        first = [reg.deterministic_split(f"글-{index}", 0.15) for index in range(50)]
        second = [reg.deterministic_split(f"글-{index}", 0.15) for index in range(50)]
        self.assertEqual(first, second)
        self.assertEqual(reg.deterministic_split("어떤 글", 0.0), "train")
        self.assertEqual(reg.deterministic_split("어떤 글", 1.0), "heldout")

    def test_repeated_build_is_byte_identical_and_merges_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            personas = root / "personas"
            tk = root / "tk.jsonl"
            _write_jsonl(
                tk,
                [
                    {"url": "https://example.test/@writer/post/CODE_A/media", "dt": "2026-01-01", "body": LONG_A},
                    {"url": "https://example.test/@writer/post/CODE_B", "dt": "2026-01-02", "body": LONG_B},
                ],
            )
            result = reg.build_registry("시험", tk, "threads", "tk-jsonl", 0.0, personas)
            registry_path = Path(result["output"])
            before = registry_path.read_bytes()
            again = reg.build_registry("시험", tk, "threads", "tk-jsonl", 0.0, personas)
            self.assertEqual(before, registry_path.read_bytes())
            self.assertEqual(again["inserted"], 0)
            self.assertEqual(again["updated"], 2)

            md = root / "notes"
            md.mkdir()
            (md / "긴 글.md").write_text(LONG_A + " 별개의 긴 글 결론이다.", encoding="utf-8")
            merged = reg.build_registry("시험", md, "longform", "md-dir", 0.0, personas)
            self.assertEqual(merged["total"], 3, "두 번째 build가 앞 매체를 덮어쓰면 안 됨")


class HygieneTests(unittest.TestCase):
    def test_tk_post_code_ignores_media_suffix(self):
        ref_a, key_a = reg._tk_ref("https://threads.test/@a/post/AAA111/media", 1)
        ref_b, key_b = reg._tk_ref("https://threads.test/@a/post/BBB222/media", 2)
        self.assertTrue(ref_a.endswith("/media"))
        self.assertEqual((key_a, key_b), ("AAA111", "BBB222"))
        self.assertNotEqual(reg.stable_id(key_a, "threads", "tk-jsonl"), reg.stable_id(key_b, "threads", "tk-jsonl"))

    def test_gn_filters_author_and_card_chrome_but_keeps_numbers_in_prose(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "raw.jsonl"
            _write_jsonl(
                source,
                [
                    {
                        "code": "GN_CODE_001",
                        "blocks": [
                            {"a": "other", "dt": "1시간", "x": "other\n남의 문장이다."},
                            {
                                "a": "specal1849",
                                "dt": "39분",
                                "x": "specal1849\nAI Threads\n39분\n·\n작성자\n좋아요 12개\n나는 39분 동안 실험하고 2가지 결과를 기록했다.\n12\n활동 보기\n남아서는 안 된다.",
                            },
                        ],
                    },
                    {"code": "NO_OWN", "blocks": [{"a": "other", "dt": "", "x": "other\n남의 글"}]},
                ],
            )
            docs = reg.load_gn_raw_jsonl(source)
        self.assertEqual(len(docs), 1)
        self.assertIn("39분 동안", docs[0]["text"])
        self.assertIn("2가지", docs[0]["text"])
        for noise in ("specal1849", "AI Threads", "작성자", "좋아요 12개", "활동 보기", "남아서는 안 된다"):
            self.assertNotIn(noise, docs[0]["text"])

    def test_threads_drops_leading_card_labels(self):
        cleaned = reg.clean_threads("AI Threads\n본문은 남아야 한다.\n@someone님에게 남긴 답글")
        self.assertEqual(cleaned, "본문은 남아야 한다.")

    def test_md_uses_relative_paths_and_actual_article_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder, ending in (("하나", "첫 결론이다."), ("둘", "둘째 결론이다.")):
                target = root / folder / "같은 이름.md"
                target.parent.mkdir()
                target.write_text(
                    "---\npublished: 2026-03-01\n---\nAI 요약: 기계가 만든 문장이다.\n\n글 전문:\n"
                    + LONG_A + " " + ending + "\n\n## 관련 노트\n제거할 꼬리",
                    encoding="utf-8",
                )
            docs = reg.load_md_dir(root)
        self.assertEqual({doc["ref"] for doc in docs}, {"하나/같은 이름.md", "둘/같은 이름.md"})
        self.assertTrue(all(doc["date"] == "2026-03-01" for doc in docs))
        self.assertTrue(all("AI 요약" not in doc["text"] and "관련 노트" not in doc["text"] for doc in docs))

    def test_md_prefers_later_complete_duplicate_passage(self):
        repeated = "이 문단은 중복 수집을 판별할 수 있을 만큼 길고 구체적인 합성 문장이다. 같은 내용이 뒤의 완전한 본문에서 다시 등장한다."
        raw = "글 전문:\n제목\n\n" + repeated + "\n\n중간의 잘린 초안\n\n" + repeated + "\n\n완전한 결론"
        cleaned, _fields = reg.clean_markdown(raw)
        self.assertEqual(cleaned.count(repeated), 1)
        self.assertNotIn("잘린 초안", cleaned)
        self.assertIn("완전한 결론", cleaned)


class SubstanceTests(unittest.TestCase):
    def test_each_low_signal_records_a_reason(self):
        link = reg.classify_substance("https://one.test\nhttps://two.test")
        self.assertEqual(link["level"], "low")
        self.assertIn("link_list_only", link["reasons"])

        reaction = reg.classify_substance("안녕하세요! 정말 반갑습니다! 좋아요! 최고예요! 오늘도 모두 힘내고 멋진 하루 보내세요!")
        self.assertEqual(reaction["level"], "low")
        self.assertIn("short_reaction_heavy", reaction["reasons"])

        repeated = reg.classify_substance("같은 문구를 길게 반복한다.\n같은 문구를 길게 반복한다.\n같은 문구를 길게 반복한다.\n다른 결론을 한 번 덧붙인다.")
        self.assertEqual(repeated["level"], "low")
        self.assertIn("repeated_phrase_gt_0.5", repeated["reasons"])

        thin = reg.classify_substance("짧지만 평범한 기록이다.")
        self.assertIn("effective_content_lt_40", thin["reasons"])

    def test_uncertain_boundary_stays_ok(self):
        text = "경계선의 글은 함부로 지우지 않는다. 구체적인 경험과 이유를 충분히 적고, 다음 행동과 판단 근거까지 차분하게 남긴다."
        self.assertEqual(reg.classify_substance(text), {"level": "ok", "reasons": []})


class PullAndStatsTests(unittest.TestCase):
    def test_pull_physically_excludes_heldout_and_low_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            personas = Path(directory) / "personas"
            path = reg.registry_path("시험", personas)
            rows = [
                _row("safe", score=0.4, topic=["도구"]),
                _row("heldout", split="heldout", score=1.0, topic=["도구"]),
                _row("low", level="low", score=1.0, topic=["도구"]),
                {**_row("unknown-split"), "split": "unknown"},
                {**_row("unknown-substance"), "substance": {"level": "unknown", "reasons": []}},
            ]
            reg.write_registry(rows, path)
            default = reg.pull_exemplars("시험", topic="도구", k=10, personas_dir=personas)
            self.assertEqual([row["id"] for row in default], ["safe"])

            heldout = reg.pull_exemplars(
                "시험", k=10, include_heldout=True, personas_dir=personas
            )
            self.assertEqual({row["id"] for row in heldout}, {"safe", "heldout"})
            low = reg.pull_exemplars(
                "시험", k=10, include_low_substance=True, personas_dir=personas
            )
            self.assertEqual({row["id"] for row in low}, {"safe", "low"})
            both = reg.pull_exemplars(
                "시험", k=10, include_heldout=True, include_low_substance=True,
                personas_dir=personas,
            )
            self.assertEqual({row["id"] for row in both}, {"safe", "heldout", "low"})

    def test_grade_then_topic_overlap_ranking_and_medium_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            personas = Path(directory) / "personas"
            path = reg.registry_path("시험", personas)
            rows = [
                _row("high", score=0.9),
                _row("topic", score=0.5, topic=["도구"]),
                _row("plain", score=0.5, topic=[]),
                _row("long", medium="longform", split="heldout", level="low"),
            ]
            reg.write_registry(rows, path)
            pulled = reg.pull_exemplars("시험", topic="도구", k=3, personas_dir=personas)
            self.assertEqual([row["id"] for row in pulled], ["high", "topic", "plain"])
            stats = reg.registry_stats("시험", personas)
        self.assertEqual(stats["schema_version"], "registry-v1")
        self.assertEqual(stats["proof_class"], "registry-measured")
        self.assertEqual(stats["by_medium"]["threads"]["total"], 3)
        self.assertEqual(stats["by_medium"]["longform"]["split"], {"heldout": 1})
        self.assertEqual(stats["by_medium"]["longform"]["substance"], {"low": 1})


class CliTests(unittest.TestCase):
    def test_stats_json_and_add_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            personas = root / "personas"
            source = root / "새 글.txt"
            source.write_text(LONG_A, encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                add_code = reg.main([
                    "add", "--persona", "시험", str(source), "--medium", "threads",
                    "--heldout-ratio", "0", "--personas-dir", str(personas),
                ])
            self.assertEqual(add_code, 0, stderr.getvalue())
            added = json.loads(stdout.getvalue())
            self.assertEqual(added["split"], "train")
            self.assertIn("schema_version", added)
            self.assertIn("proof_class", added)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                stats_code = reg.main([
                    "stats", "--persona", "시험", "--personas-dir", str(personas)
                ])
            self.assertEqual(stats_code, 0)
            measured = json.loads(stdout.getvalue())
            self.assertEqual(measured["total"], 1)
            self.assertEqual(measured["medium"], {"threads": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
