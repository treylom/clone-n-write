#!/usr/bin/env python3
"""the-author 스레드 글 종결어미 분포 카운터 (표준 라이브러리만).

정보형/홍보형 본문의 '해요체 도배'를 객관 수치로 잡는 발신 전 게이트.
형태소 분석기 없이 정규식 근사 — konlpy/mecab 금지(humanize v1.6 정책 정합).
완벽한 형태소 분류가 아니라 '본문 어미 노선'을 빠르게 진단하는 근사 도구다.

사용:
  python3 check_endings.py <file.md>            # 파일 전체
  python3 check_endings.py <file.md> --type 정보 # 유형 기대분포로 판정
  cat draft.md | python3 check_endings.py -      # stdin

유형(--type): 정보 | 사색 | 홍보 (생략 시 일반 경고만)
  정보  = 합니다+평어 주축, 해요체 ≤25% (the canonical style profile A: 정보/튜토리얼=합니다체)
  사색  = 평어+음슴 주축, 해요체 ≤15% (the canonical style profile A: 사색/논평=평어 ~다)
  홍보  = 혼합 허용, 해요체 ≤45% (the canonical style profile C: 평어도입+합니다+해요 친근)

종결체 혼용 게이트 (author policy): 정보/사색형은 한 글 안에서 종결체 일관 —
  ~습니다와 평어 ~다를 섞으면 어색. 정보=합니다 일관, 사색=평어·음슴 일관(홍보만 혼합 OK).
  '설명조 AI톤'은 종결 섞기가 아니라 명사 종결·시각기호로 깬다.

블록 마커(**①**)·제목(#)·표(|)·메타(---)·이미지([이미지)·인용(>)·차용표 줄은 제외.
"""
import re
import sys

# 종결어미 분류 — 문장 끝 기준, 우선순위 순(위에서 먼저 매칭)
# 해요체보다 합쇼체(습니다)를 먼저, 그 다음 해요체(요), 평어(다), 음슴(음)
PATTERNS = [
    ("합니다체", re.compile(r"((습니다|ㅂ니다|입니다|됩니다|합니다|십니다|랍니다|답니다|냅니다|옵니다|니까)|(?<!아)니다)[.!?…)\"']*$")),
    ("해요체",  re.compile(r"(어요|아요|에요|예요|해요|돼요|봐요|와요|줘요|이에요|거든요|네요|군요|죠|지요|구요|라구요|라고요|게요|까요|나요|는데요|걸요|군여|에여|아여|어여)[.!?…)\"']*$")),
    ("평어단정", re.compile(r"(이다|아니다|것이다|는다|ㄴ다|었다|았다|겠다|린다|한다|된다|난다|진다|친다|싶다|없다|있다|같다|버렸다|봤다|왔다|간다|온다|쓴다|든다|준다|넌다|논다|뽑는다|뜬다|는걸|더라|만다|란다|단다|났다|섰다|텄다|혔다|폈다|줬다|췄다|랐다|뒀다|썼다|뎠다|겼다|쳤다|혔다|렸다|혔다)[.!?…)\"']*$")),
    ("평어단정", re.compile(r"다[.!?…)\"']*$")),  # 폭넓은 평어(위 합니다체가 먼저 걸러짐)
    ("음슴체",  re.compile(r"(했음|였음|있음|없음|함|됨|임|음|슴)[.!?…)\"']*$")),
]

SKIP = re.compile(r"^\s*(#|\*\*[①-⑳]|\||---|>|\[이미지|!\[|title:|author:|date:|플랫폼:|톤:|블록규율:|시각|note:|벤치|정밀|상태:|페르소나|차용|source|scope|status|authors|##|변경|팩트)")

TYPE_RULE = {
    "정보": ("합니다+평어 주축", 25, ("합니다체", "평어단정")),
    "사색": ("평어+음슴 주축", 15, ("평어단정", "음슴체")),
    "홍보": ("혼합(평어도입+합니다+친근)", 45, ("평어단정", "합니다체", "해요체")),
}


def classify(sentence):
    s = sentence.strip().rstrip()
    if not s:
        return None
    for label, pat in PATTERNS:
        if pat.search(s):
            return label
    return "명사/기타"


def split_sentences(text):
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or SKIP.match(line):
            continue
        # 블록 마커 단독 줄(**①**) 제거 후 잔여
        line = re.sub(r"^\*\*[①-⑳]\*\*\s*", "", line)
        line = re.sub(r"\[이미지[^\]]*\]", "", line)
        if not line.strip():
            continue
        # 문장 분리: 종결부호 뒤에서 자름. 부호 없이 줄로 끝나면 그 줄 = 한 문장
        parts = re.split(r"(?<=[.!?…])\s+", line)
        for p in parts:
            p = p.strip()
            if len(p) >= 2:
                out.append(p)
    return out


def bar(n, total, width=24):
    if total == 0:
        return ""
    return "█" * round(n / total * width)


def main():
    args = [a for a in sys.argv[1:]]
    gtype = None
    if "--type" in args:
        i = args.index("--type")
        gtype = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    src = args[0] if args else "-"
    text = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()

    sents = split_sentences(text)
    counts = {}
    for s in sents:
        c = classify(s)
        counts[c] = counts.get(c, 0) + 1
    total = sum(counts.values())

    print(f"\n== 종결어미 분포 ({src}) — 문장 {total} ==")
    order = ["평어단정", "합니다체", "해요체", "음슴체", "명사/기타"]
    for k in order:
        n = counts.get(k, 0)
        pct = (n / total * 100) if total else 0
        print(f"  {k:<7} {n:>4} ({pct:>5.1f}%) {bar(n, total)}")

    haeyo = (counts.get("해요체", 0) / total * 100) if total else 0
    print()
    if gtype and gtype in TYPE_RULE:
        desc, cap, mains = TYPE_RULE[gtype]
        main_pct = sum(counts.get(m, 0) for m in mains) / total * 100 if total else 0
        print(f"[판정 — {gtype}형] 기대: {desc}, 해요체 ≤{cap}%")
        print(f"  · 주축({'+'.join(mains)}) = {main_pct:.1f}%")
        if haeyo > cap:
            print(f"  · ⚠️ 해요체 {haeyo:.1f}% > {cap}% — 본문 도배 의심. 사색/경험=평어, 정보=합니다로 갈라쓸 것 (the canonical style profile A·E)")
        else:
            print(f"  · ✅ 해요체 {haeyo:.1f}% ≤ {cap}% — 노선 정합")
        # 종결체 혼용 게이트 (정보/사색=한 종결체 일관, 혼용 ❌ / 홍보=혼합 OK) — author policy
        peyong = (counts.get("평어단정", 0) / total * 100) if total else 0
        hamnida = (counts.get("합니다체", 0) / total * 100) if total else 0
        eumseum = (counts.get("음슴체", 0) / total * 100) if total else 0
        if gtype == "정보" and peyong > 10 and hamnida > 10:
            print(f"  · ⚠️ 종결체 혼용 — 평어 '~다' {peyong:.0f}% + 합니다 {hamnida:.0f}% 공존. 정보형은 합니다체로 일관, 끊기는 '명사 종결'로 (~습니다/~다 섞이면 어색 — author policy)")
        elif gtype == "사색" and hamnida > 10 and (peyong + eumseum) > 10:
            print(f"  · ⚠️ 종결체 혼용 — 합니다 {hamnida:.0f}% + 평어/음슴 {peyong + eumseum:.0f}% 공존. 사색형은 평어·음슴으로 일관.")
    else:
        if haeyo > 40:
            print(f"[일반] ⚠️ 해요체 {haeyo:.1f}% — 본문 도배 의심(정보형이면 합니다/평어 주축이어야). --type으로 정밀 판정")
        else:
            print(f"[일반] 해요체 {haeyo:.1f}%. --type 정보|사색|홍보 로 정밀 판정 가능")
    print()


if __name__ == "__main__":
    main()
