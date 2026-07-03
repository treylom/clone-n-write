#!/usr/bin/env python3
"""
rewrite_loop.py — 95점 루프 (설계 §2-⑤ · §3-#6, 표준 라이브러리만).

(A) 자동 정량층(quant_scorer) + (B) 다봇 정성층(multibot_judge) 결과를 the author 5축 가중으로
합쳐 composite 산출 → <95 또는 P0/P1 → **최약 축 지목 + 축별 재작성 guidance** 반환.
실제 재생성(③ 스켈레톤 채움)은 스킬 에이전트가 수행 — 본 모듈은 결정적 진단·루프제어·모호점
질문 배치를 담당(그래야 test로 검증 가능).

the author 가중(02-progress 14:08): A·B·C 각 25 / D·E 각 12.5.
축 매핑:
  A = AI표현 부재  ← 정성 reader_eye(독자눈)·persona(문체) 평균
  B = 시작끝 연결  ← 정량 connectives (connective_lib)
  C = 시그니처 밀도 ← 정량 signature
  D = 내용 충실    ← 정성 fact_structure(fact-checker judge)
  E = 유형 프로파일 ← 정량 endings (type_profiler deviation)
"""

WEIGHTS = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.125, "E": 0.125}
MAX_ROUNDS_DEFAULT = 3

# (Phase 3.6 the author 결정 = gold-anchored bar) 전역 고정 95 ❌ — "the author 발행본(gold)이 통과하는 바".
# 장르별 gold composite(라이브 실측)에 마진 α 를 곱한 값 = 그 장르의 통과선.
# GOLD_ANCHORS = (A)quant+(B)라이브 sonnet-5 정성 composite 로 측정한 gold 값(2026-07-02 live e2e).
#   측정치라 재-측정 시 갱신(경험 앵커). 미측정 장르는 DEFAULT_ANCHOR 로 보수적 fallback.
# 정보=Threads-계열(persona 장르-fix 무관) 87.8 그대로.
# 사색=기사·논평 장문 — Phase 3.6 persona 장르인식 재-스폰(gold persona 18→78) 후 재측정 50.6.
# Example anchors — replace with scores measured on YOUR gold (published) texts
GOLD_ANCHORS = {"정보": 85.0, "사색": 50.0}
DEFAULT_ANCHOR = 80.0
PASS_FRACTION = 0.9          # gold 는 자기 바를 10% 마진으로 통과, draft 는 그 아래
PASS_BAR = 95.0             # 후방호환(genre 미지정 시 상한 참조)


def genre_bar(genre):
    """장르별 gold-anchored 통과선 = min(95, anchor × α)."""
    anchor = GOLD_ANCHORS.get(genre, DEFAULT_ANCHOR)
    return round(min(95.0, anchor * PASS_FRACTION), 1)

# 축 → (재작성 대상 설명, 구체 지시). 지시는 connective_lib/type_profiler/signature 소비를 가리킴.
_AXIS_FIX = {
    "A": ("AI표현(경구·대구 마무리·매끈한 추상비유·collocation 봇티)",
          "딱 떨어지는 경구형 마무리·'산더미' 류 추상 비유를 실질 이유·구체 상황으로 교체. gate collocation 재확인."),
    "B": ("시작끝 연결(예고-받기·수미상관·다음편 훅 이음말)",
          "connective_lib 이음말로 블록 끝에 예고 질문 → 다음 블록이 받기, 도입↔'정리하면' 수미상관, 다음편 훅 삽입."),
    "C": ("시그니처 밀도(작은따옴표·말줄임·해서,·구요/거든요·번호목록·도구 구체노출)",
          "top_phrases 유형별 최빈 시그니처를 주입 — the author이 실제 자주 쓰는 표현·번호목록·슬래시명령 구체노출."),
    "D": ("내용 충실(사실·구조·출처)",
          "원자재 사실 왜곡·누락 보정, 근거·출처 명시, 논리 구조 보강(fact-checker judge verdict 참조)."),
    "E": ("유형 프로파일(종결어미 노선)",
          "type_profiler 목표 분포로 종결어미 교정 — 유형별 해요 cap 준수·주축 어미 일관(정보=합니다/사색=평어)."),
}


def _axis_scores(quant, judge):
    per = judge.get("per_role", {})
    reader = per.get("reader_eye")
    persona = per.get("persona")
    ap = [x for x in (reader, persona) if isinstance(x, (int, float))]
    A = round(sum(ap) / len(ap), 1) if ap else 0.0
    fact = per.get("fact_structure")
    D = float(fact) if isinstance(fact, (int, float)) else 0.0
    return {
        "A": A,
        "B": float(quant.get("connectives", 0)),
        "C": float(quant.get("signature", 0)),
        "D": D,
        "E": float(quant.get("endings", 0)),
    }


def composite(quant, judge, genre=None):
    """5축 가중합 + pass/gate/최약축.

    (Phase 3.6) pass = composite ≥ **gold-anchored 장르바** AND **P0 없음**.
      - 게이트 = **P0 only**(원 설계 §2 "<bar or P0" 정합). P1 은 감점·재작성 신호이되 hard-fail ❌
        — 라이브에서 gold(the author 발행본)가 P1(그런데 반복·이중주파수 부재)로 fail 하던 과-게이트 해소.
      - 바 = genre_bar(genre)(장르별 gold×α). genre 미지정 시 PASS_BAR(95) 후방호환.
    ⚠️ 타당성 위협(code-quality §7): GOLD_ANCHORS 는 **장르당 gold 1편(n=1)** 라이브 실측 기반 —
       노이즈 있음. 코퍼스 gold 가 늘면 앵커를 분위수/다편 평균으로 재산정할 것(하드코딩 ceiling).
    """
    axes = _axis_scores(quant, judge)
    comp = round(sum(axes[k] * WEIGHTS[k] for k in WEIGHTS), 1)
    defects = judge.get("defects", [])
    grades = {d.get("grade") for d in defects}
    p0 = "P0" in grades
    bar = genre_bar(genre) if genre else PASS_BAR
    weakest = min(axes, key=lambda k: axes[k])
    return {
        "axes": axes,
        "composite": comp,
        "bar": bar,
        "genre": genre,
        "pass": comp >= bar and not p0,
        "gated": p0,                                   # P0 만 hard-gate(설계 §2)
        "gate_reason": "P0(치명)" if p0 else ("P1(감점·비게이트)" if "P1" in grades else ""),
        "weakest_axis": weakest,
        "defects": defects,
    }


def rewrite_guidance(comp_result):
    """최약 축(또는 결함 축) 지목 + 구체 재작성 지시."""
    axis = comp_result["weakest_axis"]
    what, instruction = _AXIS_FIX[axis]
    return {
        "axis": axis,
        "what": what,
        "instruction": instruction,
        "score": comp_result["axes"][axis],
        "defects": comp_result.get("defects", []),
    }


def should_continue(comp_result, rounds_done, max_rounds=MAX_ROUNDS_DEFAULT):
    """루프 지속 여부 — pass면 정지, max_rounds 도달하면 정지(무한 방지)."""
    if comp_result["pass"]:
        return False
    return rounds_done < max_rounds


def batch_questions(questions):
    """모호점을 한 번에 많이 — 번호 매긴 질문 묶음(사용자에게 1회 발신용)."""
    return "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))


if __name__ == "__main__":
    import json
    q = {"endings": 92, "connectives": 40, "signature": 88}
    j = {"per_role": {"reader_eye": 90, "persona": 93, "fact_structure": 91}, "defects": []}
    r = composite(q, j)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("guidance:", rewrite_guidance(r)["axis"], rewrite_guidance(r)["what"])
