#!/usr/bin/env python3
"""
test_type_profiler.py — 글종류 판정 + 유형별 목표 분포 + 범용 라벨 스키마 흡수 (TDD).

실행: python3 test_type_profiler.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import type_profiler as tp  # noqa: E402


class TestProfileSchema(unittest.TestCase):
    def test_author_genres_present(self):
        for g in ("사색", "정보", "홍보", "후기", "에세이"):
            self.assertIn(g, tp.PROFILES, f"기본 장르 {g} 누락")

    def test_haeyo_caps_align_with_check_endings(self):
        # check_endings TYPE_RULE 정합: 정보25 / 사색15 / 홍보45
        self.assertEqual(tp.target_profile("정보")["haeyo_cap"], 25)
        self.assertEqual(tp.target_profile("사색")["haeyo_cap"], 15)
        self.assertEqual(tp.target_profile("홍보")["haeyo_cap"], 45)

    def test_each_profile_has_required_keys(self):
        for g, prof in tp.PROFILES.items():
            for k in ("haeyo_cap", "main_endings", "length_band", "signature_emphasis"):
                self.assertIn(k, prof, f"{g}: {k} 누락")


class TestGenericAbsorption(unittest.TestCase):
    """example-persona-B 카테고리를 유형 라벨 스키마로 흡수 — 범용 설계 실증."""

    def test_gonyangi_aliases_resolve_to_genres(self):
        self.assertEqual(tp.resolve_label("AI팁"), "정보")
        self.assertEqual(tp.resolve_label("잡담"), "사색")
        self.assertEqual(tp.resolve_label("비즈니스"), "홍보")
        self.assertEqual(tp.resolve_label("에세이"), "에세이")

    def test_unknown_label_falls_back(self):
        self.assertEqual(tp.resolve_label("듣도보도못한장르"), tp.DEFAULT_GENRE)

    def test_register_new_persona_schema(self):
        # 새 페르소나가 자기 라벨→장르 매핑을 등록(코퍼스 넣는 구조 §4)
        tp.register_aliases({"튜토리얼": "정보", "일기": "사색"})
        self.assertEqual(tp.resolve_label("튜토리얼"), "정보")
        self.assertEqual(tp.resolve_label("일기"), "사색")


class TestClassify(unittest.TestCase):
    def test_declared_label_wins(self):
        # 선언된 라벨(별칭 포함)이 있으면 그대로(별칭 resolve)
        self.assertEqual(tp.classify("아무 텍스트", declared="AI팁"), "정보")

    def test_infer_from_ending_distribution(self):
        info = "이 기능은 이렇게 동작합니다. 먼저 설치합니다. 그다음 실행합니다. 결과가 출력됩니다."
        musing = "오늘은 좀 다르다. 결국 다 지나간다. 나는 그렇게 느꼈다. 삶이란 그런 거다."
        self.assertEqual(tp.classify(info), "정보")
        self.assertEqual(tp.classify(musing), "사색")


class TestDeviation(unittest.TestCase):
    def test_deviation_returns_axis_numbers(self):
        text = "이 기능은 이렇게 동작합니다. 먼저 설치합니다. 그다음 실행합니다."
        dev = tp.deviation(text, "정보")
        self.assertIn("haeyo_pct", dev)
        self.assertIn("haeyo_over_cap", dev)
        self.assertIn("main_ending_pct", dev)
        self.assertIsInstance(dev["haeyo_over_cap"], bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
