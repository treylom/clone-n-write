#!/usr/bin/env python3
"""
test_humanize_whitelist.py — the-author 시그니처 보호막 TDD (설계 §3-#7, 결함 a 마무리).

범용 humanize-korean 이 the author 시그니처(...·"해서,"·작은따옴표·ㅎㅎ·구요/거든요)를
'AI 티'로 오인해 깎지 않도록, humanize 전에 protect() 로 보호 → 후에 restore().
실행: python3 test_humanize_whitelist.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import humanize_whitelist as hw  # noqa: E402


class TestProtectedSpans(unittest.TestCase):
    def test_finds_signatures(self):
        text = "저도 그랬거든요... '연결'이 먼저예요. 해서, 만들었구요 ㅎㅎ"
        found = hw.protected_spans(text)
        kinds = {k for _, _, _, k in found}
        self.assertIn("말줄임", kinds)
        self.assertIn("작은따옴표", kinds)
        self.assertIn("해서,", kinds)
        self.assertIn("ㅎㅎ/ㅋㅋ", kinds)

    def test_plain_text_no_protection(self):
        self.assertEqual(hw.protected_spans("저장은 중요하다 연결도 중요하다"), [])


class TestRoundTrip(unittest.TestCase):
    def test_protect_then_restore_is_identity(self):
        text = "저도 처음엔 그냥 모으기만 했거든요... '진짜 알맹이'는 연결이에요. 해서, 만들었죠 ㅋㅋ"
        wrapped, mapping = hw.protect(text)
        # 보호 구간은 sentinel 로 치환됨
        self.assertNotEqual(wrapped, text)
        self.assertIn(hw.SENTINEL_PREFIX, wrapped)
        # 복원하면 원문 동일(내용 불변 — 윤문가가 sentinel 은 안 건드린다는 전제)
        self.assertEqual(hw.restore(wrapped, mapping), text)

    def test_restore_after_humanizer_edits_nonprotected(self):
        text = "이건 정말 좋은 것 같아요... 그래서 추천해요."
        wrapped, mapping = hw.protect(text)
        # 윤문가가 비보호 구간만 바꿨다고 가정(sentinel 보존)
        edited = wrapped.replace("정말 좋은 것 같아요", "꽤 괜찮아요")
        out = hw.restore(edited, mapping)
        self.assertIn("...", out)               # 말줄임 시그니처 복원됨
        self.assertIn("꽤 괜찮아요", out)          # 윤문 반영됨

    def test_sentinels_are_unique(self):
        text = "하나... 둘... 셋..."
        wrapped, mapping = hw.protect(text)
        self.assertEqual(wrapped.count(hw.SENTINEL_PREFIX), 3)
        self.assertEqual(len(mapping), 3)


class TestInstruction(unittest.TestCase):
    def test_humanize_instruction_mentions_sentinel(self):
        instr = hw.humanize_instruction()
        self.assertIn(hw.SENTINEL_PREFIX, instr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
