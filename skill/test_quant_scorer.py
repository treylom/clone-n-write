#!/usr/bin/env python3
"""
test_quant_scorer.py — 자동 정량 채점층(설계 §2-④A·§3-#3) TDD.

축: ① 종결어미 프로파일 편차 ② 시작끝 연결(connective_lib) ③ 시그니처 밀도.
지표가 신호에 반응하는지(verify-metric-sensitivity) = 위반본 < 정합본 실증.
실행: python3 test_quant_scorer.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quant_scorer as qs  # noqa: E402


class TestEndingsAxis(unittest.TestCase):
    def test_aligned_info_scores_high(self):
        info = "이 기능은 이렇게 동작합니다. 먼저 설치합니다. 그다음 실행합니다. 결과가 출력됩니다."
        self.assertGreaterEqual(qs.score_endings(info, "정보"), 80)

    def test_haeyo_flood_in_info_scores_lower(self):
        flood = "이거 해봤어요. 진짜 좋아요. 신기했어요. 다들 써봐요. 완전 편해요."
        aligned = "이 기능은 이렇게 동작합니다. 먼저 설치합니다. 그다음 실행합니다."
        self.assertLess(qs.score_endings(flood, "정보"),
                        qs.score_endings(aligned, "정보"))


class TestConnectivesAxis(unittest.TestCase):
    PUB = [
        "2편에서 구조를 짰다면 이제 자료를 쌓을 차례입니다. 어떻게 잘 저장해야 할까요?",
        "AI가 잘 읽으려면, 어떻게 저장돼 있어야 할까요? 우선 안 좋은 예부터 봅니다.",
        "그런데 막상 저장하려면 손이 갑니다.",
        "정리하면, 저장은 길을 까는 일입니다. 다음 편에서는 검색을 풀어 보겠습니다.",
    ]
    ABRUPT = [
        "자료를 저장하는 방법입니다.",
        "안 좋은 예부터 봅니다.",
        "knowledge-manager를 씁니다.",
        "GIGO 원칙이 있습니다.",
    ]

    def test_pub_higher_than_abrupt(self):
        self.assertGreater(qs.score_connectives(self.PUB),
                           qs.score_connectives(self.ABRUPT))


class TestSignatureAxis(unittest.TestCase):
    def test_detects_author_markers(self):
        rich = "저도 처음엔 그냥 모으기만 했거든요... '연결'이 먼저예요. 그래서 만들었구요."
        bare = "저장은 중요하다. 연결도 중요하다. 방법은 여러 가지다."
        self.assertGreater(qs.score_signature(rich, "사색"),
                           qs.score_signature(bare, "사색"))


class TestCompositeScore(unittest.TestCase):
    def test_score_returns_all_axes(self):
        r = qs.score("이 기능은 이렇게 동작합니다. 먼저 설치합니다.", "정보")
        for k in ("endings", "signature", "overall", "genre"):
            self.assertIn(k, r)

    def test_blocks_add_connective_axis(self):
        r = qs.score("\n".join(TestConnectivesAxis.PUB), "정보",
                     blocks=TestConnectivesAxis.PUB)
        self.assertIn("connectives", r)
        self.assertGreater(r["connectives"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
