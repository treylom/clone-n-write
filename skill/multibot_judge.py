#!/usr/bin/env python3
"""
multibot_judge.py — (B) 다봇 정성 채점층 (설계 §2-④B · §3-#5, 표준 라이브러리만).

3심 정성 심사: 자동 정량층(quant_scorer)이 못 보는 '사람이 쓴 글인가·사실이 맞나·문체가
the author인가'를 다봇이 판정. 본 모듈 책임 = **role 프롬프트 + verdict JSON 파싱 + 정성 aggregate**.
실제 심사자 스폰은 두 경로:
  - 공개판: Workflow 서브에이전트 **sonnet-5 필수**(설계 §4·the author 명시) — 3 role 각 1 스폰.
  - the author 개인판: fact-checker judge(Codex)·reader-POV judge(Antigravity) 실봇 연결(e2e·#4에서).
스킬 오케스트레이션이 build_prompt()로 각 role 프롬프트를 만들어 스폰→응답을 parse_verdict()→
aggregate()로 (B) 정성 점수. rewrite-loop(#2)이 (A)quant+(B)qual 가중합으로 95 게이트.
"""
import json
import re

PUBLIC_JUDGE_MODEL = "sonnet-5"  # 공개판 Workflow 서브에이전트 모델(the author 명시)

JUDGE_ROLES = {
    "fact_structure": {
        "name": "fact-checker judge 역할",
        "focus": "사실·구조·출처 정확성",
        "instruction": ("원자재 사실이 왜곡·과장 없이 보존됐나, 논리 구조가 탄탄한가, "
                        "출처·근거가 확인 가능한가. 사실 왜곡·날조=P0, 근거 없는 단정=P1."),
    },
    "reader_eye": {
        "name": "reader-POV judge 역할",
        "focus": "독자눈 — 사람이 쓴 글로 읽히는가",
        "instruction": ("일반 독자가 읽었을 때 'AI가 썼다'는 느낌이 드는 구간이 있나. "
                        "경구형 마무리·매끈한 추상 비유·기계적 병렬 등 AI티=감점. 자연스러운 사람 글이면 고점."),
    },
    "persona": {
        "name": "the-author 문체 역할",
        "focus": "문체 정합 — the author다움",
        "instruction": ("종결어미 노선(유형별)·시그니처(작은따옴표·말줄임·해서,·구요/거든요)·"
                        "이중 주파수(저는→우리)·시작끝 연결이 the author 발행본과 정합하나. "
                        "⚠️ 장르 인식(Phase 3.6): Threads 전용 시그니처(말줄임·이중주파수 '저는→우리'·"
                        "ㅎㅎ 등)의 *부재*를 **기사·에세이·논평 등 장문/객관 장르에 그대로 감점하지 말 것** — "
                        "그 장르는 원래 그 시그니처를 안 쓴다(the author 기사도 마찬가지). 해당 장르에선 "
                        "격식·논리 전개·1인칭 관점 유지 같은 *그 장르에 맞는* 문체 정합을 본다."),
    },
}

_ANCHOR = ("점수 앵커: 0=미시도 / 50=약함·부분 / 90=기대 규율 충족+근거 인용 / 95+=탁월(반사적으로 정답). "
           "결함: P0=치명(사실왜곡·명백 AI티)·P1=주요(규율 스킵)·P2=경미.")


def build_prompt(role, draft, genre="", rubric="", profile="", quant=""):
    """role별 심사 프롬프트. 스킬이 이걸로 서브에이전트(공개판=sonnet-5) 스폰."""
    r = JUDGE_ROLES[role]
    parts = [
        f"당신은 '{r['name']}'({r['focus']}) 심사자입니다. the author 글을 채점하세요.",
        f"심사 관점: {r['instruction']}",
        _ANCHOR,
    ]
    if genre:
        parts.append(f"글종류: {genre} (그 종류의 목표 프로파일 기준으로 판정).")
    if profile:
        parts.append(f"목표 프로파일: {profile}")
    if quant:
        parts.append(f"자동 정량 점수(참고): {quant}")
    if rubric:
        parts.append(f"루브릭:\n{rubric}")
    parts.append("서술로 근거를 먼저 쓰고, 마지막에 JSON 한 블록으로 닫으세요: "
                 '```json\\n{"role":"%s","score":<0-100>,"defects":[{"grade":"P0|P1|P2","desc":"..."}],"evidence":["..."]}\\n```' % role)
    parts.append("--- 채점 대상 초안 ---\n" + draft)
    return "\n\n".join(parts)


def parse_verdict(text, role):
    """심사자 응답 텍스트에서 마지막 JSON 블록 추출 → verdict dict. 실패 시 score=None."""
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    raw = blocks[-1] if blocks else None
    if raw is None:
        m = re.search(r"(\{[^{}]*\"score\"[^{}]*\})", text, flags=re.S)
        raw = m.group(1) if m else None
    if raw is None:
        return {"role": role, "score": None, "defects": [], "evidence": [], "raw": text[:200]}
    try:
        d = json.loads(raw)
    except Exception:
        return {"role": role, "score": None, "defects": [], "evidence": [], "raw": raw[:200]}
    d.setdefault("role", role)
    d.setdefault("defects", [])
    d.setdefault("evidence", [])
    if not isinstance(d.get("score"), (int, float)):
        d["score"] = None
    return d


def aggregate(verdicts):
    """정성 점수 = role 점수 평균(None 제외) + P0/P1 게이트."""
    scored = [v["score"] for v in verdicts if isinstance(v.get("score"), (int, float))]
    qualitative = round(sum(scored) / len(scored), 1) if scored else None
    defects = [d for v in verdicts for d in v.get("defects", [])]
    grades = {d.get("grade") for d in defects}
    gated = "P0" in grades or "P1" in grades
    reason = ""
    if "P0" in grades:
        reason = "P0(치명 — 사실왜곡·명백 AI티)"
    elif "P1" in grades:
        reason = "P1(주요 규율 스킵)"
    return {
        "qualitative": qualitative,
        "per_role": {v.get("role"): v.get("score") for v in verdicts},
        "defects": defects,
        "gated": gated,
        "gate_reason": reason,
    }


if __name__ == "__main__":
    print("roles:", list(JUDGE_ROLES), "| public model:", PUBLIC_JUDGE_MODEL)
    print(build_prompt("persona", "샘플 초안입니다.", genre="사색")[:300])
