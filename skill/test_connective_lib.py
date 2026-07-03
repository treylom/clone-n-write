#!/usr/bin/env python3
"""
test_connective_lib.py — connective_lib 정본 하드와이어 회귀 테스트 (TDD, 표준 라이브러리만).

목적(설계 결함 b 재유실 방지): 2026-06-13 v3에서 실제 글에서 추출한
예고/받기/수미상관/경계 이음말 어휘가 정본(40-final·thread-style)에 전파되지 못하고
한 회의 draft에만 남아 '잃어버린 fix'가 됐다. 본 테스트가 그 어휘를 코드 정본에 못박아
카테고리·핵심 어휘가 사라지면 CI/실행에서 즉시 RED가 나게 한다.

실행: python3 test_connective_lib.py   (스킬 폴더에서)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import connective_lib as cl  # noqa: E402


# 정본 카테고리 — 이 6개가 사라지면 = 재유실 = RED (하드와이어)
CANON_CATEGORIES = {
    "forward_cue",       # 예고: 블록 끝 앞으로 던지는 질문
    "pickup",            # 받기: 다음 블록이 그 질문을 받아 시작
    "bookend",           # 수미상관: 도입 논지 ↔ 마무리 회수
    "inter_block",       # 500자 경계 이음말(블록 전환)
    "next_part_hook",    # 다음 편 예고 훅
    "closing_move",      # 마무리 수(후속 약속·유머 점프·커뮤니티 감사) — v3 20-qual
}


class TestCanonPresence(unittest.TestCase):
    """정본 어휘 존재 보장 — 재유실 가드."""

    def test_all_canon_categories_present(self):
        self.assertEqual(CANON_CATEGORIES, set(cl.CONNECTIVES.keys()),
                         "정본 connective 카테고리가 사라지거나 바뀜 = 결함 b 재유실")

    def test_every_category_has_patterns_and_examples(self):
        for cat, spec in cl.CONNECTIVES.items():
            self.assertTrue(spec.get("patterns"), f"{cat}: 탐지 패턴 비어있음")
            self.assertTrue(spec.get("examples"), f"{cat}: 예시 어휘 비어있음(생성 소비 불가)")
            self.assertTrue(spec.get("source"), f"{cat}: 출처(정본 근거) 누락")

    def test_phrases_accessor_returns_generation_vocab(self):
        # 생성 소비: 카테고리별 예시 어휘 반환
        self.assertIn("정리하면", " ".join(cl.phrases("bookend")))
        self.assertTrue(cl.phrases())  # 전체


class TestDetectGoldenPhrases(unittest.TestCase):
    """LLM-Wiki 3편 발행본(the author 최종)의 실제 이음말이 탐지되어야 한다 (금맥 b)."""

    def test_bookend_detected(self):
        hits = cl.detect("정리하면, 저장은 'AI가 다닐 길(링크)을 깔아 주는 일'입니다.")
        self.assertIn("bookend", hits)

    def test_next_part_hook_detected(self):
        hits = cl.detect("다음 편에서는 '이렇게 저장한 걸 어떻게 잘 검색하게 만드는지'를 풀어 보겠습니다.")
        self.assertIn("next_part_hook", hits)

    def test_forward_cue_detected(self):
        hits = cl.detect("어떻게 llm wiki에 자료들을 잘 저장해야 할까요?")
        self.assertIn("forward_cue", hits)

    def test_inter_block_transition_detected(self):
        hits = cl.detect("그런데 막상 저장하려고 하면, 손이 꽤 많이 갑니다.")
        self.assertIn("inter_block", hits)

    def test_closing_move_detected(self):
        # v3 20-qual 마무리 패턴: 후속 약속 / 겸손
        hits = cl.detect("물론 정답인 방법은 없고, 저도 아직 다듬어 가는 중이에요.")
        self.assertIn("closing_move", hits)

    def test_no_false_positive_on_plain_sentence(self):
        hits = cl.detect("AI는 원본을 의심하지 않거든요.")
        self.assertNotIn("bookend", hits)
        self.assertNotIn("next_part_hook", hits)


class TestAnalyzeBlocks(unittest.TestCase):
    """블록 리스트의 시작끝 연결 커버리지 = (b) 채점 신호."""

    # 발행본 3편 블록의 축약(경계 이음말·수미상관·다음편 훅 포함)
    PUB_BLOCKS = [
        "2편에서 구조를 짰다면, 이제 자료를 쌓을 차례입니다. 어떻게 잘 저장해야 할까요?",
        "AI가 llm wiki를 잘 읽으려면, 어떻게 저장돼 있어야 할까요? 우선 안 좋은 예부터 보겠습니다.",
        "그런데 막상 저장하려고 하면 손이 꽤 많이 갑니다.",
        "그래서 저는 knowledge-manager라는 스킬을 만들어 씁니다.",
        "정리하면, 저장은 길을 까는 일입니다. 다음 편에서는 검색을 풀어 보겠습니다.",
    ]
    # 뚝뚝 끊긴 블록(이음말·수미상관·다음편 훅 없음) — 낮은 커버리지가 나와야
    ABRUPT_BLOCKS = [
        "자료를 저장하는 방법입니다.",
        "안 좋은 예부터 봅니다.",
        "knowledge-manager를 씁니다.",
        "GIGO 원칙이 있습니다.",
    ]

    def test_published_blocks_have_high_bridge_coverage(self):
        r = cl.analyze_blocks(self.PUB_BLOCKS)
        self.assertTrue(r["bookend"], "발행본은 수미상관(정리하면) 있어야")
        self.assertTrue(r["next_part_hook"], "발행본은 다음편 훅 있어야")
        self.assertGreaterEqual(r["transition_ratio"], 0.5,
                                "발행본 블록 경계 이음말 비율이 낮음")

    def test_abrupt_blocks_score_lower(self):
        pub = cl.analyze_blocks(self.PUB_BLOCKS)
        abr = cl.analyze_blocks(self.ABRUPT_BLOCKS)
        self.assertGreater(pub["transition_ratio"], abr["transition_ratio"],
                           "뚝뚝 끊긴 블록이 발행본보다 이음 비율이 낮아야(=(b) 판별력)")
        self.assertFalse(abr["next_part_hook"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
