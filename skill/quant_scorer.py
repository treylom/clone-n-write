#!/usr/bin/env python3
"""
quant_scorer.py — 자동 정량 채점층 (설계 §2-④(A) · §3-#3, 표준 라이브러리만).

3겹 채점 중 '자동 정량층(결정적)'. check_endings(어미)·type_profiler(유형 프로파일)·
connective_lib(시작끝 연결)을 조합해 축별 0-100 점수를 낸다.
  ① 종결어미 프로파일 편차 (type_profiler.deviation)
  ② 시작끝 연결 커버리지 ((b) 축 — connective_lib.analyze_blocks)
  ③ 시그니처 밀도 (the-author 지문: 작은따옴표·말줄임·해서·구요/거든요 등)

⚠️ check_endings.py 를 직접 확장하지 않고 별 모듈로 둔 이유: type_profiler 가 이미
check_endings 를 import 하므로, check_endings 가 type_profiler 를 import 하면 순환 참조.
본 모듈이 세 leaf(check_endings·type_profiler·connective_lib)를 조합하는 상위층 = 설계 §3
"quant-scorer(check_endings 축 확장)"의 무순환 구현.

AI표현 부재(collocation 0-gram)는 gate.py(#4) 담당 — 본 모듈은 positive 축만.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import type_profiler as tp          # noqa: E402
import connective_lib as cl         # noqa: E402

# the-author 시그니처 지문(밀도 축). 카테고리별 1개+ 있으면 '살아있음'.
_SIG = {
    "작은따옴표": re.compile(r"'[^']{1,30}'"),
    "말줄임": re.compile(r"(…|\.\.+)"),
    "해서,": re.compile(r"(^|[.!?…]\s*)해서,"),
    "구요/거든요": re.compile(r"(구요|라구요|거든요)[.!?…)\s]"),
    "죠": re.compile(r"(죠|지요)[.!?…)\s]"),
    "ㅎㅎ/ㅋㅋ": re.compile(r"(ㅎ{2,}|ㅋ{2,})"),
}


def _clamp(x):
    return max(0.0, min(100.0, x))


def score_endings(text, genre):
    """① 종결어미 프로파일 편차 → 0-100. 해요 cap 초과·주축 부족을 감점."""
    dev = tp.deviation(text, genre)
    score = 100.0
    over = dev["haeyo_pct"] - dev["haeyo_cap"]
    if over > 0:
        score -= over * 1.5          # 해요 도배 감점(장르 caps 정합)
    deficit = 40 - dev["main_ending_pct"]
    if deficit > 0:
        score -= deficit * 0.8       # 주축 어미 부족 감점
    return round(_clamp(score), 1)


def score_connectives(blocks):
    """② 시작끝 연결 → 0-100. (Phase 3.5 보정) **의도적 브리지 중심**.

    예고 질문(forward_cue)·받기(pickup)·수미상관(bookend)·다음편 훅을 주로 보상하고,
    기계적 오프너(그런데/그래서 = transition_ratio)는 15%로 축소. 근거: e2e 반전 —
    구 formula(transition_ratio 70)는 draft의 기계적 ①-블록 오프너를 the author 산문 예고-받기보다
    높게 매겼다(3편 gold 65<draft 79). 예고-받기 pair 를 핵심 신호로 재설계.
    """
    r = cl.analyze_blocks(blocks)
    score = 0.0
    score += min(40, r["forward_cue_blocks"] * 20)        # 예고 질문(핵심 (b) 신호)
    score += 15 if r["pickup_blocks"] > 0 else 0          # 받기
    score += 15 if r["bookend"] else 0                    # 수미상관
    score += 15 if r["next_part_hook"] else 0             # 다음편 훅
    score += r["transition_ratio"] * 15                   # 기계 오프너 = 소폭(축소)
    return round(_clamp(score), 1)


def score_signature(text, genre):
    """③ 시그니처 밀도 → 0-100. 서로 다른 지문 종류 수(존재)·밀도 반영. 장르 무관 base."""
    distinct = sum(1 for pat in _SIG.values() if pat.search(text))
    # 지문 3종+ = 충분(100), 선형 스케일
    presence = min(100.0, distinct / 3 * 100)
    return round(presence, 1)


def score(text, genre, blocks=None):
    """축별 + overall. blocks 주면 연결 축 포함(단일 텍스트면 어미·시그니처만).

    (Phase 3.5 보정) endings 는 **자동 판정 장르**의 cap 으로 채점 — 선언 장르가 텍스트 실제
    문체와 안 맞으면(예: the author 정보글의 자연스러운 높은 해요) 과벌점이 되어 gold 를 깎던 반전 해소.
    선언 genre 는 reporting·시그니처 emphasis 용 hint 로만.
    """
    declared = tp.classify(text, declared=genre) if genre else tp.classify(text)
    auto = tp.classify(text)   # endings cap = 텍스트 실제 fit(자동 판정)
    axes = {
        "endings": score_endings(text, auto),
        "signature": score_signature(text, declared),
    }
    if blocks:
        axes["connectives"] = score_connectives(blocks)
    axes["overall"] = round(sum(axes.values()) / len(axes), 1)
    axes["genre"] = auto          # endings 채점에 쓴 자동 판정 장르
    axes["declared_genre"] = declared
    return axes


if __name__ == "__main__":
    import json
    demo_blocks = [
        "2편에서 구조를 짰다면 이제 자료를 쌓을 차례입니다. 어떻게 잘 저장해야 할까요?",
        "그런데 막상 저장하려면 손이 갑니다.",
        "정리하면, 저장은 길을 까는 일입니다. 다음 편에서는 검색을 풀어 보겠습니다.",
    ]
    print(json.dumps(score("\n".join(demo_blocks), "정보", blocks=demo_blocks),
                     ensure_ascii=False, indent=2))
