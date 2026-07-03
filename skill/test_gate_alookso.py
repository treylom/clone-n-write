#!/usr/bin/env python3
"""
test_gate_alookso.py — gate.py 얼룩소 확장 + collocation 단위 AI티(word 오탐 제거) TDD.

설계 결함 (a): 게이트=Threads 전용(얼룩소 자동게이트 0) + banned-phrase가 word 단위라
'알맹이'(word)까지 오탐(collocation '진짜 알맹이'만 봇티). → media 판정 + collocation-only 필터.
기존 base-provenance/borrow/pass 계약은 불변(additive).
실행: python3 test_gate_alookso.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402


class TestMediaDetection(unittest.TestCase):
    def test_alookso_by_frontmatter_platform(self):
        draft = "---\nplatform: AlookSo\n---\n긴 에세이 본문입니다."
        self.assertEqual(gate.detect_media(draft, "/x/essay.md"), "alookso")

    def test_threads_by_block_markers(self):
        draft = "**①**\n첫 블록\n**②**\n둘째 블록\n**③**\n셋째"
        self.assertEqual(gate.detect_media(draft, "/x/thread.md"), "threads")

    def test_alookso_by_path(self):
        draft = "본문만 있는 글"
        self.assertEqual(gate.detect_media(draft, "/vault/<longform-dir>/글.md"), "alookso")

    def test_default_threads(self):
        draft = "짧은 글"
        self.assertEqual(gate.detect_media(draft, "/x/note.md"), "threads")


class TestCollocationFilter(unittest.TestCase):
    """word 오탐 제거 = 단일 단어 flag 드롭, 2+토큰 collocation만 advisory 유지."""

    def test_single_word_dropped(self):
        self.assertFalse(gate.keep_collocation("알맹이"))
        self.assertFalse(gate.keep_collocation("껍데기"))

    def test_collocation_kept(self):
        self.assertTrue(gate.keep_collocation("진짜 알맹이"))
        self.assertTrue(gate.keep_collocation("서로 이어져"))

    def test_filter_drops_word_flags_only(self):
        raw = ["알맹이", "진짜 알맹이", "껍데기", "정리해 줘"]
        kept = [f for f in raw if gate.keep_collocation(f)]
        self.assertEqual(kept, ["진짜 알맹이", "정리해 줘"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
