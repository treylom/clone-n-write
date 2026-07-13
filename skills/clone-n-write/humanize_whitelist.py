#!/usr/bin/env python3
"""
humanize_whitelist.py — the-author 시그니처 보호막 (설계 §3-#7, 결함 a 마무리, 표준 라이브러리만).

문제: 범용 humanize-korean 은 the author 시그니처(말줄임 …·"해서,"·작은따옴표 '…'·ㅎㅎ·구요/거든요)를
'AI 티/구어체 오류'로 오인해 깎아낼 수 있다(오히려 페르소나 소실). → humanize 돌리기 *전에*
시그니처를 sentinel 로 protect() → humanize 후 restore(). 윤문가에겐 "sentinel 토큰은 절대
건드리지 말라"고 지시(humanize_instruction).

정합: quant_scorer._SIG·connective_lib 와 같은 시그니처 정의(중복 최소화 위해 여기 명시).
"""
import re

SENTINEL_PREFIX = "⟦TKSIG"
SENTINEL_SUFFIX = "⟧"

# 보호 대상 시그니처(kind, 패턴). the author 지문 — humanize 가 깎으면 페르소나 소실.
SIGNATURE_PATTERNS = [
    ("작은따옴표", re.compile(r"'[^']{1,30}'")),
    ("말줄임", re.compile(r"(…|\.\.+)")),
    ("해서,", re.compile(r"해서,")),
    ("ㅎㅎ/ㅋㅋ", re.compile(r"(ㅎ{2,}|ㅋ{2,})")),
    ("구요/거든요/죠", re.compile(r"(거든요|더라구요|라구요|구요|지요|죠)(?=[\s.!?…)\"']|$)")),
]


def protected_spans(text):
    """비겹침 보호 구간 [(start,end,token,kind)] — start 오름차순."""
    spans = []
    for kind, pat in SIGNATURE_PATTERNS:
        for m in pat.finditer(text):
            spans.append((m.start(), m.end(), m.group(0), kind))
    # start 오름차순, 동일 start 는 긴 것 우선
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out, last_end = [], -1
    for s in spans:
        if s[0] >= last_end:
            out.append(s)
            last_end = s[1]
    return out


def protect(text):
    """시그니처를 unique sentinel 로 치환. 반환 (wrapped, {sentinel: 원문토큰})."""
    spans = protected_spans(text)
    mapping = {}
    result = text
    for idx in range(len(spans) - 1, -1, -1):     # 뒤에서부터 치환(offset 보존)
        st, en, tok, _kind = spans[idx]
        sent = f"{SENTINEL_PREFIX}{idx}{SENTINEL_SUFFIX}"
        mapping[sent] = tok
        result = result[:st] + sent + result[en:]
    return result, mapping


def restore(wrapped, mapping):
    """sentinel 을 원문 시그니처로 복원."""
    for sent, tok in mapping.items():
        wrapped = wrapped.replace(sent, tok)
    return wrapped


def humanize_instruction():
    """humanize 서브에이전트(korean-style-rewriter 등)에 붙이는 보호 지시."""
    return (f"⚠️ 보호 토큰: `{SENTINEL_PREFIX}<n>{SENTINEL_SUFFIX}` 형태의 sentinel 은 "
            "the-author 고유 시그니처(말줄임·작은따옴표·해서,·ㅎㅎ·구요/거든요)를 감싼 것이다. "
            "**절대 수정·삭제·이동하지 말고 그 자리에 그대로 둘 것.** 그 외 구간만 자연스럽게 윤문한다. "
            "sentinel 을 AI 티로 오인해 제거하면 페르소나가 소실된다.")


if __name__ == "__main__":
    t = "저도 처음엔 그냥 모으기만 했거든요... '진짜 알맹이'는 연결이에요. 해서, 만들었죠 ㅋㅋ"
    w, m = protect(t)
    print("wrapped:", w)
    print("mapping:", m)
    print("restore == orig:", restore(w, m) == t)
