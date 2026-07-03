#!/usr/bin/env python3
"""
connective_lib.py — the-author 이음말(연결어) 정본 라이브러리 (표준 라이브러리만).

설계 결함 (b) 복원·정본화 (설계 히스토리):
  the author 글의 강점 중 하나는 블록/문단이 뚝뚝 끊기지 않고 **예고→받기→수미상관**으로 이어진다는
  것. 이 이음말 어휘를 초기 버전에서 실제 글에서 추출했으나 정본 스타일 가이드에 전파 못 해
  '잃어버린 fix'가 됐다(설계 §1 결함 b). 본 lib이 그 어휘를 **코드 정본**으로 못박고,
  생성(이음말 예시 제공)·채점(이음 커버리지 측정) 양쪽이 소비한다.
  재유실은 `test_connective_lib.py`(하드와이어 회귀)가 RED로 차단.

근거(정본):
  - 발행 시리즈의 이음말 구조(예고 질문·수미상관·다음편 훅) — 본 파일 예문은 전부 합성.
    Phase 0 금맥 diff(v5 gate-PASS ↔ 발행본)에서 the author이 *추가*한 이음이 여기 해당.
  - 내부 정성 분석 doc — 훅→전개→마무리 구조 + 마무리 수
    (후속 약속·유머 점프·커뮤니티 감사)·이어쓰기 네이티브 폼.

소비:
  - 생성: `phrases(category)` — 카테고리별 예시 이음말 어휘.
  - 채점: `detect(text)` — 한 텍스트에 어떤 이음 카테고리가 있나 / `analyze_blocks(blocks)` —
    블록 리스트의 시작끝 연결 커버리지((b) 축 신호).
"""
import re

_SRC_PUB = "synthetic examples (same connective shape as the author's published series)"
_SRC_V3 = "internal qualitative analysis doc"

# 정본 이음말 카탈로그. 각 카테고리: description·patterns(탐지)·examples(생성)·source(근거).
CONNECTIVES = {
    "forward_cue": {
        "description": "예고 — 블록 끝에서 앞으로 던지는 질문(다음 블록을 여는 갈고리).",
        "patterns": [
            re.compile(r"(할까요|해야 할까요|을까요|ㄹ까요|볼까요|일까요)\s*[?？]"),
            re.compile(r"(어떻게|왜|무엇을|뭘)\s.{0,40}(까요|나요)\s*[?？]"),
        ],
        "examples": [
            "어떻게 사진들을 한곳에 잘 모아야 할까요?",
            "그런데 모으기만 하면, 나중에 잘 찾을 수 있을까요?",
            "그럼 이걸 어떻게 다시 꺼내 쓸까요?",
        ],
        "source": _SRC_PUB,
    },
    "pickup": {
        "description": "받기 — 다음 블록이 앞 질문을 되받아(조건절·되묻기) 시작.",
        "patterns": [
            re.compile(r"(려면|자면)[,·]?\s*(어떻게|무엇|왜|어디|얼마)"),
            re.compile(r"^\s*(우선|먼저)[,\s]"),
        ],
        "examples": [
            "도구가 기록을 잘 읽으려면, 어떻게 정리돼 있어야 할까요? 우선, 안 좋은 예부터 보겠습니다.",
            "그걸 하려면, 어디부터 손대야 할까요?",
        ],
        "source": _SRC_PUB,
    },
    "bookend": {
        "description": "수미상관 — 도입 논지를 마무리에서 회수(정리하면/요약하면).",
        "patterns": [
            re.compile(r"(^|\s)(정리하면|요약하면|한마디로|결론적으로|다시 정리하면)"),
        ],
        "examples": [
            "정리하면, 기록은 '나중의 나에게 길을 깔아 주는 일'입니다.",
            "요약하면, 핵심은 꾸준함이에요.",
        ],
        "source": _SRC_PUB,
    },
    "inter_block": {
        "description": "500자 경계 이음말 — 블록 전환을 여는 접속(그런데/그래서/게다가…).",
        "patterns": [
            re.compile(r"^\s*(그런데|그래서|그리고|게다가|그러니|근데|자,|이제|그럼|조금 더|그런데 여기서|사실)"),
        ],
        "examples": [
            "그런데 막상 시작하려고 하면, 손이 꽤 많이 갑니다.",
            "그래서 저는 작은 도구를 하나 만들어 씁니다.",
            "그런데 여기서 제일 중요한 걸 말씀드리겠습니다.",
        ],
        "source": _SRC_PUB,
    },
    "next_part_hook": {
        "description": "다음 편 예고 훅 — 연재 다음 화를 문제의식과 함께 예고.",
        "patterns": [
            re.compile(r"다음\s?(편|글|화|번)|다음엔|이어서 다음|다음 회"),
        ],
        "examples": [
            "다음 편에서는 '모아 둔 걸 어떻게 다시 꺼내 쓰는지'를 풀어 보겠습니다.",
            "이건 다음 글에서 더 자세히 풀어볼게요.",
        ],
        "source": _SRC_PUB,
    },
    "closing_move": {
        "description": "마무리 수 — 후속 약속·겸손·유머 점프·커뮤니티 감사(v3 20-qual 귀납).",
        "patterns": [
            re.compile(r"(다시 (포스팅|올리|쓰겠|공유)|후속|아직 다듬|계속 고쳐|고쳐 나가는 중|정답은 없|정답인 방법은 없|"
                       r"봐주셔서 감사|읽어주셔서 감사|여러분 덕분|ㅋㅋ+|허허)"),
        ],
        "examples": [
            "물론 정답은 없고, 저도 계속 고쳐 나가는 중이에요.",
            "더 나은 방법을 알게 되면 다시 공유할게요.",
            "봐주셔서 감사합니다!",
        ],
        "source": _SRC_V3,
    },
}


def phrases(category=None):
    """생성 소비: 카테고리별(또는 전체) 예시 이음말 어휘."""
    if category is None:
        out = []
        for spec in CONNECTIVES.values():
            out.extend(spec["examples"])
        return out
    return list(CONNECTIVES.get(category, {}).get("examples", []))


def detect(text):
    """채점 소비: 텍스트에 존재하는 이음 카테고리 집합."""
    hits = {}
    for cat, spec in CONNECTIVES.items():
        for pat in spec["patterns"]:
            m = pat.search(text)
            if m:
                hits.setdefault(cat, []).append(m.group(0).strip())
                break
    return hits


def _last_sentence(block):
    parts = re.split(r"(?<=[.!?…?？])\s+", block.strip())
    return parts[-1] if parts else block.strip()


def _ends_forward_cue(block):
    last = _last_sentence(block)
    return any(p.search(last) for p in CONNECTIVES["forward_cue"]["patterns"])


def _has_forward_cue(block):
    """블록 내 *어느* 문장이든 예고 질문이면 True (Phase 3.5: the author 산문은 문단 중간에 예고 질문)."""
    return any(p.search(block) for p in CONNECTIVES["forward_cue"]["patterns"])


def _starts(block, category):
    return any(p.search(block.strip()) for p in CONNECTIVES[category]["patterns"])


def analyze_blocks(blocks):
    """블록 리스트의 시작끝 연결 커버리지 = (b) 채점 신호.

    반환:
      bookend / next_part_hook : bool (글 전체에 수미상관·다음편 훅 있나)
      forward_cue_blocks / pickup_blocks : int
      bridged_boundaries / boundaries : int
      transition_ratio : float — 인접 블록 경계 중 이음(전환어/받기/앞블록 예고/수미상관)이 있는 비율
    """
    blocks = [b for b in blocks if b and b.strip()]
    n = len(blocks)
    full = "\n".join(blocks)
    bookend = any(p.search(full) for p in CONNECTIVES["bookend"]["patterns"])
    next_hook = any(p.search(full) for p in CONNECTIVES["next_part_hook"]["patterns"])
    fc = sum(1 for b in blocks if _has_forward_cue(b))   # 문단 중간 예고 질문 포함(Phase 3.5)
    pk = sum(1 for i, b in enumerate(blocks) if i > 0 and _starts(b, "pickup"))

    boundaries = max(0, n - 1)
    bridged = 0
    for i in range(1, n):
        cur, prev = blocks[i], blocks[i - 1]
        if (_starts(cur, "inter_block") or _starts(cur, "pickup")
                or _starts(cur, "bookend") or _has_forward_cue(prev)):
            bridged += 1
    ratio = (bridged / boundaries) if boundaries else 0.0
    return {
        "bookend": bookend,
        "next_part_hook": next_hook,
        "forward_cue_blocks": fc,
        "pickup_blocks": pk,
        "bridged_boundaries": bridged,
        "boundaries": boundaries,
        "transition_ratio": round(ratio, 3),
    }


if __name__ == "__main__":
    import json
    demo = [
        "지난 글에서 틀을 짰다면 이제 채울 차례입니다. 어떻게 잘 채워야 할까요?",
        "AI가 잘 읽으려면, 어떻게 저장돼 있어야 할까요? 우선 안 좋은 예부터 봅니다.",
        "그런데 막상 시작하려면 손이 갑니다.",
        "정리하면, 저장은 길을 까는 일입니다. 다음 편에서는 검색을 풀어 보겠습니다.",
    ]
    print(json.dumps(analyze_blocks(demo), ensure_ascii=False, indent=2))
