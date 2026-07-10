#!/usr/bin/env python3
"""Synthetic-only tests for the v2 exemplar registry."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
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

    def test_default_split_is_three_way_and_ratio_extremes_are_exact(self):
        observed = {reg.deterministic_split(f"v2-{index}") for index in range(100)}
        self.assertEqual(observed, set(reg.SPLITS))
        self.assertNotIn("heldout", observed)
        self.assertEqual(reg.deterministic_cluster_split("cluster", (1, 0, 0)), "train")
        self.assertEqual(reg.deterministic_cluster_split("cluster", (0, 1, 0)), "dev")
        self.assertEqual(reg.deterministic_cluster_split("cluster", (0, 0, 1)), "final")

    def test_ratios_reject_nan_and_infinity(self):
        for ratios in ("nan,0,0", "inf,0,0", "-inf,1,0"):
            with self.subTest(ratios=ratios):
                with self.assertRaisesRegex(reg.RegistryError, "finite"):
                    reg.normalize_split_ratios(ratios)

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


class ThreeWayMigrationTests(unittest.TestCase):
    @staticmethod
    def _with_body(row, body, **fields):
        row = {**row, **fields, "body": body, "chars": len(body)}
        return row

    def test_all_three_cluster_signals_are_component_invariants(self):
        common_prefix = "근사 중복을 판별하는 충분히 긴 문장입니다. " * 12
        rows = [
            self._with_body(
                _row("series-title", topic=["독립-a"]),
                "제목에만 태그가 있는 첫 글입니다.",
                title="[정치학, 껌이지] 1화",
            ),
            self._with_body(
                _row("series-body", topic=["독립-b"]),
                "# [정치학, 껌이지]\n본문 첫 줄의 마크다운 태그도 같은 연재입니다.",
            ),
            self._with_body(
                _row("topic-a", topic=["alpha", "beta", "gamma", "delta"]),
                "토픽 그룹 첫 번째 서로 다른 본문입니다.",
            ),
            self._with_body(
                _row("topic-b", topic=["alpha", "beta", "gamma", "epsilon"]),
                "토픽 그룹 두 번째 서로 다른 본문입니다.",
            ),
            self._with_body(_row("near-a", topic=[]), common_prefix + "A 결론"),
            self._with_body(_row("near-b", topic=[]), common_prefix + "B 결론"),
            self._with_body(
                _row("other", topic=["다른-주제"]),
                "[오리미중]\n어느 그룹과도 겹치지 않는 본문입니다.",
            ),
        ]
        assigned = reg.assign_cluster_splits(rows)
        by_id = {row["id"]: row for row in assigned}
        for left, right in (
            ("series-title", "series-body"),
            ("topic-a", "topic-b"),
            ("near-a", "near-b"),
        ):
            self.assertEqual(by_id[left]["cluster_id"], by_id[right]["cluster_id"])
            self.assertEqual(by_id[left]["split"], by_id[right]["split"])
        self.assertNotEqual(by_id["other"]["cluster_id"], by_id["series-title"]["cluster_id"])

        reversed_assignment = reg.assign_cluster_splits(list(reversed(rows)))
        reversed_by_id = {
            row["id"]: (row["cluster_id"], row["split"])
            for row in reversed_assignment
        }
        self.assertEqual(
            {row_id: (row["cluster_id"], row["split"]) for row_id, row in by_id.items()},
            reversed_by_id,
        )

    def test_resplit_is_in_place_with_exact_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            personas = Path(directory) / "personas"
            path = reg.registry_path("시험", personas)
            rows = [
                {**_row("one", split="heldout"), "title": "[오리미중] 1화"},
                self._with_body(
                    _row("two", split="train"),
                    "## [오리미중]\n두 번째 연재 본문입니다.",
                ),
            ]
            reg.write_registry(rows, path)
            before = path.read_bytes()
            result = reg.resplit_registry("시험", (0, 1, 0), personas)

            self.assertEqual(Path(result["backup"]).read_bytes(), before)
            migrated = reg.load_registry(path)
            self.assertEqual({row["split"] for row in migrated}, {"dev"})
            self.assertEqual(len({row["cluster_id"] for row in migrated}), 1)
            self.assertEqual(result["split"], {"dev": 2})

    def test_pull_defaults_train_and_final_requires_explicit_unseal(self):
        with tempfile.TemporaryDirectory() as directory:
            personas = Path(directory) / "personas"
            path = reg.registry_path("시험", personas)
            reg.write_registry(
                [_row("train", split="train"), _row("dev", split="dev"), _row("final", split="final")],
                path,
            )
            self.assertEqual(
                [row["id"] for row in reg.pull_exemplars("시험", k=10, personas_dir=personas)],
                ["train"],
            )
            self.assertEqual(
                [row["id"] for row in reg.pull_exemplars(
                    "시험", k=10, personas_dir=personas, split="dev"
                )],
                ["dev"],
            )
            with self.assertRaisesRegex(reg.RegistryError, "final split is sealed"):
                reg.pull_exemplars("시험", k=10, personas_dir=personas, split="final")
            final = reg.pull_exemplars(
                "시험", k=10, personas_dir=personas, split="final", unseal_final=True
            )
            self.assertEqual([row["id"] for row in final], ["final"])
            heldout_compat = reg.pull_exemplars(
                "시험", k=10, include_heldout=True, personas_dir=personas
            )
            self.assertEqual({row["id"] for row in heldout_compat}, {"train", "dev"})

    def test_add_returns_only_a_sealed_receipt_for_final(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            personas = root / "personas"
            source = root / "final.txt"
            source.write_text(LONG_A, encoding="utf-8")
            receipt = reg.add_exemplar(
                "시험", source, "threads", personas_dir=personas, ratios=(0, 0, 1)
            )
            self.assertEqual(receipt["split"], "final")
            self.assertTrue(receipt["sealed"])
            self.assertNotIn("body", receipt)
            stored = reg.load_registry(reg.registry_path("시험", personas))
            self.assertEqual(stored[0]["split"], "final")
            self.assertIn("body", stored[0])

    def test_incremental_add_and_build_do_not_reopen_a_sealed_final_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            personas = root / "personas"
            first = next(
                root / f"first-{index}.txt"
                for index in range(100)
                if reg.deterministic_cluster_split(
                    hashlib.sha1(
                        reg.stable_id(
                            str((root / f"first-{index}.txt").resolve()), "threads", "add"
                        ).encode("utf-8")
                    ).hexdigest()
                ) == "train"
            )
            first.write_text(
                "첫 번째 예시는 실제 작업의 맥락과 판단 근거를 충분히 담아 독립적으로 작성합니다. "
                "세부적인 결과와 한계도 차분하게 설명해 완결성을 갖춥니다.",
                encoding="utf-8",
            )
            sealed = reg.add_exemplar(
                "시험", first, "threads", personas_dir=personas, ratios=(0, 0, 1)
            )
            self.assertEqual(sealed["split"], "final")

            second = root / "second.txt"
            second.write_text(
                "두 번째 예시는 다른 맥락에서 얻은 관찰과 선택의 이유를 상세히 기록합니다. "
                "첫 번째 글과 관계없이 결과를 검토하고 다음 행동을 정리합니다.",
                encoding="utf-8",
            )
            reg.add_exemplar("시험", second, "threads", personas_dir=personas)

            source = root / "third.jsonl"
            _write_jsonl(
                source,
                [{
                    "url": "https://example.test/@writer/post/THIRD",
                    "dt": "2026-01-03",
                    "body": "세 번째 예시는 수집 과정에서 추가된 독립적인 기록입니다. "
                            "관찰한 사실과 해석의 근거를 충분히 남겨 다음 판단에 활용합니다.",
                }],
            )
            reg.build_registry("시험", source, "threads", "tk-jsonl", personas_dir=personas)

            rows = reg.load_registry(reg.registry_path("시험", personas))
            first_id = reg.stable_id(str(first.resolve()), "threads", "add")
            self.assertEqual(
                next(row["split"] for row in rows if row["id"] == first_id), "final"
            )

    def test_incremental_split_conflicts_keep_the_component_final(self):
        rows = [
            self._with_body(_row("train", split="train"), "[같은 연재] 첫 글입니다."),
            self._with_body(_row("final", split="final"), "[같은 연재] 마지막 글입니다."),
        ]
        assigned = reg.assign_incremental_cluster_splits(
            rows, {"train": "train", "final": "final"}, (1, 0, 0)
        )
        self.assertEqual({row["split"] for row in assigned}, {"final"})


class CliTests(unittest.TestCase):
    def test_resplit_cli_accepts_comma_ratios(self):
        with tempfile.TemporaryDirectory() as directory:
            personas = Path(directory) / "personas"
            path = reg.registry_path("시험", personas)
            reg.write_registry([_row("one", split="heldout")], path)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = reg.main([
                    "resplit", "--persona", "시험",
                    "--ratios", "0.7,0.15,0.15",
                    "--personas-dir", str(personas),
                ])

            self.assertEqual(code, 0, stderr.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["ratios"], {"train": 0.7, "dev": 0.15, "final": 0.15})
            self.assertTrue(Path(result["backup"]).is_file())

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
