#!/usr/bin/env python3
"""
test_multibot_judge.py — (B) 다봇 정성 채점층 TDD (설계 §2-④B·§3-#5).

3심: fact-checker judge(사실·구조·출처) / reader-POV judge(독자눈: 사람글인가) / persona(문체).
모듈 책임 = role 프롬프트 제공 + verdict JSON 파싱 + 정성 aggregate + P0/P1 게이트.
실제 스폰(공개판=Workflow sonnet-5)은 스킬 오케스트레이션·e2e 담당.
실행: python3 test_multibot_judge.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import multibot_judge as mj  # noqa: E402


class TestRoles(unittest.TestCase):
    def test_three_roles(self):
        self.assertEqual({"fact_structure", "reader_eye", "persona"}, set(mj.JUDGE_ROLES))

    def test_public_model_is_sonnet5(self):
        self.assertEqual(mj.PUBLIC_JUDGE_MODEL, "sonnet-5")

    def test_build_prompt_includes_draft_and_focus(self):
        p = mj.build_prompt("reader_eye", draft="테스트 초안 본문", genre="사색")
        self.assertIn("테스트 초안 본문", p)
        self.assertIn(mj.JUDGE_ROLES["reader_eye"]["focus"], p)

    def test_persona_prompt_is_genre_aware(self):
        """Phase 3.6: persona 프롬프트에 장르 인식(기사·에세이엔 Threads 시그니처 잣대 ❌) 포함."""
        p = mj.build_prompt("persona", draft="기사 본문", genre="사색")
        self.assertIn("장르", p)
        self.assertTrue("기사" in p or "장문" in p)


class TestParseVerdict(unittest.TestCase):
    def test_parse_json_block(self):
        text = ('심사 이유 서술...\n'
                '```json\n{"role":"persona","score":88,"defects":[],"evidence":["해요체 일관"]}\n```')
        v = mj.parse_verdict(text, role="persona")
        self.assertEqual(v["score"], 88)
        self.assertEqual(v["role"], "persona")

    def test_parse_missing_json_is_none_score(self):
        v = mj.parse_verdict("JSON 없음", role="persona")
        self.assertIsNone(v["score"])


class TestAggregate(unittest.TestCase):
    def test_mean_of_role_scores(self):
        verds = [
            {"role": "fact_structure", "score": 90, "defects": []},
            {"role": "reader_eye", "score": 80, "defects": []},
            {"role": "persona", "score": 94, "defects": []},
        ]
        r = mj.aggregate(verds)
        self.assertEqual(r["qualitative"], 88.0)
        self.assertFalse(r["gated"])

    def test_p0_gates_regardless_of_scores(self):
        verds = [
            {"role": "fact_structure", "score": 95, "defects": [{"grade": "P0", "desc": "사실왜곡"}]},
            {"role": "reader_eye", "score": 95, "defects": []},
            {"role": "persona", "score": 95, "defects": []},
        ]
        r = mj.aggregate(verds)
        self.assertTrue(r["gated"])
        self.assertIn("P0", r["gate_reason"])

    def test_missing_verdict_excluded_from_mean(self):
        verds = [
            {"role": "fact_structure", "score": 90, "defects": []},
            {"role": "reader_eye", "score": None, "defects": []},
            {"role": "persona", "score": 80, "defects": []},
        ]
        r = mj.aggregate(verds)
        self.assertEqual(r["qualitative"], 85.0)  # None 제외 평균


if __name__ == "__main__":
    unittest.main(verbosity=2)
