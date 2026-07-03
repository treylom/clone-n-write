#!/usr/bin/env python3
"""
type_profiler.py — 글종류(장르) 판정 + 유형별 목표 분포표 (표준 라이브러리만).

설계(author policy "주제마다 다르다"):
  단일 rubric ❌ → 글종류를 먼저 판정하고 그 종류의 목표 분포로 채점·생성한다.
  종결어미 caps 는 check_endings.py TYPE_RULE 과 정합(정보25/사색15/홍보45).

🔌 범용 라벨 스키마 흡수 (orchestrator-bot 지시): 장르 프로파일은 the-author 5종을 기본 제공하되,
  라벨→장르 별칭(ALIASES)이 pluggable — example-persona-B 카테고리(AI팁/잡담/에세이/
  비즈니스/홍보)가 자연 흡수되고(2번째 페르소나 케이스, 설계 §4 "사용자 자기 코퍼스"),
  Phase 1 top-phrases-by-type 의 '주제/소스 근사' ceiling(장르 매핑 부재)도 이 층이 메운다.
  새 페르소나는 register_aliases()로 자기 라벨 매핑을 등록.

소비: quant-scorer(#3)가 deviation(text, genre)로 프로파일 대비 편차를 점수화.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_endings import classify as classify_ending, split_sentences  # noqa: E402  어미분류 SoT 재사용

DEFAULT_GENRE = "사색"

# 장르별 목표 프로파일. haeyo_cap=check_endings TYPE_RULE 정합.
# main_endings = (primary, secondary) 순 — 판정·편차 가중에 primary 2배.
PROFILES = {
    "정보": {
        "haeyo_cap": 25,
        "main_endings": ("합니다체", "평어단정"),
        "length_band": (400, 3000),
        "signature_emphasis": ["번호목록", "도구·명령 구체노출", "inter_block"],
        "note": "정보/튜토리얼 = 합니다체 일관(40-final A). 명사 종결로 끊고 해요 남발 ❌.",
    },
    "사색": {
        "haeyo_cap": 15,
        "main_endings": ("평어단정", "음슴체"),
        "length_band": (300, 5000),
        "signature_emphasis": ["말줄임", "작은따옴표", "bookend"],
        "note": "사색/논평 = 평어·음슴 위주(40-final A). 단정을 말줄임으로 눌러 여운.",
    },
    "홍보": {
        "haeyo_cap": 45,
        "main_endings": ("평어단정", "합니다체"),
        "length_band": (200, 2000),
        "signature_emphasis": ["해서,", "closing_move", "next_part_hook"],
        "note": "홍보 = 평어 도입 + 합니다 + 해요 친근 혼합(40-final C).",
    },
    "후기": {
        "haeyo_cap": 45,
        "main_endings": ("해요체", "합니다체"),
        "length_band": (500, 4000),
        "signature_emphasis": ["사회적좌표 도입", "관계형 CTA", "격식·친근 혼합"],
        "note": "후기·관점 = 6규칙(사회적좌표·격식/친근 혼합·본인 1인칭·관계형 CTA).",
    },
    "에세이": {
        "haeyo_cap": 35,
        "main_endings": ("평어단정", "해요체"),
        "length_band": (800, 8000),
        "signature_emphasis": ["작은따옴표", "이중 레지스터", "bookend"],
        "note": "에세이 = 평어+해요 혼합(얼룩소 에세이-개인 실측 해요 18.6%·~죠 9.9 최고).",
    },
}

# 라벨 → 장르 별칭. example-persona-B 카테고리 흡수(범용 설계 실증) + the-author 자체 라벨.
ALIASES = {
    # example-persona-B 카테고리
    "AI팁": "정보",
    "잡담": "사색",
    "에세이": "에세이",
    "비즈니스": "홍보",
    "홍보": "홍보",
    # the-author Threads 유형 별칭
    "정보": "정보", "사색": "사색", "후기": "후기",
    "튜토리얼": "정보", "논평": "사색", "관점": "사색",
}


def register_aliases(mapping):
    """새 페르소나가 자기 라벨→장르 매핑 등록(설계 §4 '사용자 자기 코퍼스' 구조)."""
    ALIASES.update(mapping)


def resolve_label(label):
    """라벨(별칭 포함)을 기본 장르로 해석. 미상 = DEFAULT_GENRE."""
    if not label:
        return DEFAULT_GENRE
    label = label.strip()
    if label in PROFILES:
        return label
    return ALIASES.get(label, DEFAULT_GENRE)


def target_profile(genre):
    """장르(또는 별칭)의 목표 프로파일."""
    return PROFILES[resolve_label(genre)]


def ending_pcts(text):
    """텍스트의 종결어미 분포(%) — check_endings 분류 재사용."""
    sents = split_sentences(text)
    counts = {}
    for s in sents:
        c = classify_ending(s)
        if c:
            counts[c] = counts.get(c, 0) + 1
    total = sum(counts.values()) or 1
    return {k: counts.get(k, 0) / total * 100
            for k in ("평어단정", "합니다체", "해요체", "음슴체", "명사/기타")}


def classify(text, declared=None):  # noqa: F811  (check_endings.classify는 위에서 sentence용, 여긴 글종류용)
    """글종류 판정. declared(별칭 포함)가 있으면 우선, 없으면 어미 분포로 추론."""
    if declared:
        return resolve_label(declared)
    dist = ending_pcts(text)
    best, best_score = DEFAULT_GENRE, -1.0
    for genre, prof in PROFILES.items():
        primary, secondary = prof["main_endings"]
        score = dist.get(primary, 0) * 2 + dist.get(secondary, 0)
        if dist.get("해요체", 0) > prof["haeyo_cap"]:
            score -= 20  # 해요 과다 = 그 장르답지 않음
        if score > best_score:
            best, best_score = genre, score
    return best


def deviation(text, genre):
    """프로파일 대비 편차 — quant-scorer(#3) 소비. 실제 분포 vs 목표."""
    prof = target_profile(genre)
    dist = ending_pcts(text)
    primary, secondary = prof["main_endings"]
    haeyo = dist.get("해요체", 0)
    return {
        "genre": resolve_label(genre),
        "haeyo_pct": round(haeyo, 1),
        "haeyo_cap": prof["haeyo_cap"],
        "haeyo_over_cap": haeyo > prof["haeyo_cap"],
        "main_ending_pct": round(dist.get(primary, 0) + dist.get(secondary, 0), 1),
        "dist": {k: round(v, 1) for k, v in dist.items()},
        "length": len(text),
        "length_band": prof["length_band"],
        "length_in_band": prof["length_band"][0] <= len(text) <= prof["length_band"][1],
    }


if __name__ == "__main__":
    import json
    samples = {
        "AI팁(example-persona-B→정보)": ("설치는 이렇게 합니다. 먼저 켭니다. 그다음 실행합니다.", "AI팁"),
        "사색(추론)": ("오늘은 좀 다르다. 결국 다 지나간다. 나는 그렇게 느꼈다.", None),
    }
    for name, (t, decl) in samples.items():
        g = classify(t, declared=decl)
        print(name, "→", g, "|", json.dumps(deviation(t, g), ensure_ascii=False))
