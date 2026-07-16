#!/usr/bin/env python3
"""
test_rewrite_loop.py — 95점 루프 (A정량+B정성 가중합→축지목 재작성) TDD (설계 §2-⑤·§3-#6).

the author 가중(02-progress 14:08): A·B·C 각25 / D·E 각12.5.
축: A=AI표현부재(reader_eye+persona) B=시작끝(connectives) C=시그니처(signature)
    D=내용충실(fact_structure) E=유형프로파일(endings).
실행: python3 test_rewrite_loop.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rewrite_loop as rl  # noqa: E402


def _quant(endings=95, connectives=95, signature=95):
    return {"endings": endings, "connectives": connectives, "signature": signature}


def _judge(reader=95, persona=95, fact=95, defects=None):
    return {"per_role": {"reader_eye": reader, "persona": persona, "fact_structure": fact},
            "defects": defects or [], "gated": bool(defects), "qualitative": (reader + persona + fact) / 3}


class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(rl.WEIGHTS.values()), 1.0, places=6)

    def test_weight_values(self):
        self.assertEqual(rl.WEIGHTS["A"], 0.25)
        self.assertEqual(rl.WEIGHTS["E"], 0.125)


class TestComposite(unittest.TestCase):
    def test_all_high_passes(self):
        r = rl.composite(_quant(), _judge())
        self.assertGreaterEqual(r["composite"], 95)
        self.assertTrue(r["pass"])

    def test_low_connectives_flags_axis_B(self):
        r = rl.composite(_quant(connectives=40), _judge())
        self.assertEqual(r["weakest_axis"], "B")
        self.assertFalse(r["pass"])

    def test_low_endings_flags_axis_E(self):
        r = rl.composite(_quant(endings=30), _judge())
        self.assertEqual(r["weakest_axis"], "E")

    def test_p0_gates_regardless(self):
        r = rl.composite(_quant(), _judge(defects=[{"grade": "P0", "desc": "사실왜곡"}]))
        self.assertFalse(r["pass"])
        self.assertTrue(r["gated"])

    def test_axis_A_uses_reader_and_persona(self):
        r = rl.composite(_quant(), _judge(reader=50, persona=50))
        self.assertEqual(r["axes"]["A"], 50.0)


class TestGoldAnchoredBar(unittest.TestCase):
    """Phase 3.6: 전역 95 ❌ → gold-anchored 장르별 바 + P0-only 게이트."""

    def test_genre_bar_values(self):
        self.assertEqual(rl.genre_bar("정보"), 76.5)   # 85.0×0.9 (example anchor)
        self.assertEqual(rl.genre_bar("사색"), 45.0)   # 50.0×0.9 (persona 장르-fix 후 재측정)
        self.assertEqual(rl.genre_bar("홍보"), 72.0)   # default 80×0.9

    def test_p1_does_not_gate(self):
        """P1 은 감점·재작성 신호이되 hard-fail ❌ (원 설계 <bar or P0). gold P1 fail 회귀 해소."""
        r = rl.composite(_quant(connectives=90), _judge(reader=85, persona=80,
                         defects=[{"grade": "P1", "desc": "그런데 반복"}]), genre="정보")
        self.assertFalse(r["gated"])            # P1 은 게이트 아님
        self.assertTrue(r["pass"])              # 바 넘으면 P1 있어도 통과

    def test_p0_still_gates(self):
        r = rl.composite(_quant(), _judge(defects=[{"grade": "P0", "desc": "사실왜곡"}]), genre="정보")
        self.assertTrue(r["gated"])
        self.assertFalse(r["pass"])

    def test_gold_passes_draft_fails_at_genre_bar(self):
        # 라이브 실측 재현: 정보 gold(85.0) pass / draft(67.9) fail (bar 79)
        gold = rl.composite(_quant(endings=100, connectives=93, signature=100),
                            _judge(reader=62, persona=60), genre="정보")
        draft = rl.composite(_quant(endings=100, connectives=40, signature=100),
                             _judge(reader=58, persona=52), genre="정보")
        self.assertTrue(gold["pass"])
        self.assertFalse(draft["pass"])


class TestGuidanceAndLoop(unittest.TestCase):
    def test_guidance_targets_weakest_axis(self):
        r = rl.composite(_quant(connectives=40), _judge())
        g = rl.rewrite_guidance(r)
        self.assertEqual(g["axis"], "B")
        self.assertIn("이음말", g["instruction"] + g["what"])

    def test_should_continue_stops_on_pass(self):
        passed = rl.composite(_quant(), _judge())
        self.assertFalse(rl.should_continue(passed, rounds_done=0, max_rounds=3))

    def test_should_continue_stops_at_max_rounds(self):
        failing = rl.composite(_quant(connectives=10), _judge())
        self.assertFalse(rl.should_continue(failing, rounds_done=3, max_rounds=3))
        self.assertTrue(rl.should_continue(failing, rounds_done=1, max_rounds=3))

    def test_ambiguity_questions_batched(self):
        qs = rl.batch_questions(["매체가 Threads인가 얼룩소인가?", "링크를 넣나?"])
        self.assertIn("1.", qs)
        self.assertIn("2.", qs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
