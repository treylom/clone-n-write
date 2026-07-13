#!/usr/bin/env python3
"""
check_corpus_phrases.py — 드래프트의 collocation(구) provenance 게이트 (report-only).

원리(설계 히스토리): 봇 표현 신호는 *단어*가 아니라 *콜로케이션*이다.
  - '알맹이'(단어) = the author 실어휘 → 차단 ❌ (word-blocklist는 false-positive 제조)
  - '진짜 알맹이'(2-gram) = the author 발행 corpus 0건 → 봇 전용 → FLAG
∴ 통합 corpus(build_corpus.py 산출)에 *0건인 2~3그램*만 리포트한다. **report-only**(hard-block ❌).
josa(조사·종결어미)는 마지막 토큰에서 근사 strip 후 대조(표준 라이브러리만).

사용: python3 check_corpus_phrases.py <draft.md> [--top 40]
선행: python3 build_corpus.py  (corpus/the-author-corpus.txt 생성)
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus", "the-author-corpus.txt")

# 마지막 토큰 josa/종결 근사 strip (긴 것 우선)
SUFFIXES = sorted([
    '입니다','습니다','거든요','더라구요','더라고요','이에요','이예요','잖아요','이라는','이라고',
    '구요','네요','어요','예요','에요','라고','라는','으로','에서','에게','한테','까지','부터','처럼','보다',
    '이다','이야','죠','은','는','이','가','을','를','의','에','도','만','와','과','요','님','들',
], key=len, reverse=True)

def strip_josa(tok):
    for s in SUFFIXES:
        if len(tok) > len(s) + 1 and tok.endswith(s):
            return tok[:-len(s)]
    return tok

def load_corpus():
    if not os.path.exists(CORPUS):
        sys.exit(f"❌ corpus 없음: {CORPUS}\n   먼저 `python3 build_corpus.py` 실행")
    t = open(CORPUS, encoding='utf-8').read()
    return re.sub(r'\s+', ' ', t)            # 공백 단일화 (substring 대조용)

def corpus_freq(corpus):
    """corpus 단어 빈도(josa-normalized) — 어휘 멤버십 + distinctive(저빈도) 판정용."""
    from collections import Counter
    c = Counter(strip_josa(w) for w in words(corpus))
    return c

DISTINCT_MAX = 8   # corpus 빈도 ≤8 = the author distinctive 어휘(흔한 단어 노이즈 배제)

def draft_body(path):
    t = open(path, encoding='utf-8').read()
    t = re.sub(r'^---\n.*?\n---\n', '', t, flags=re.S)   # frontmatter
    # 본문 블록만(메타/변경표 제외): '## 본문' 이후 '## ' 전까지 있으면 그 구간
    m = re.search(r'##\s*본문.*?\n(.*?)(?:\n##\s|\Z)', t, flags=re.S)
    if m:
        t = m.group(1)
    t = re.sub(r'\*\*[①-⑪]\*\*.*', '', t)               # 블록마커 라인 잔여
    t = re.sub(r'\[이미지[^\]]*\]', ' ', t)
    return t

def words(s):
    s = re.sub(r"[^\w가-힣']+", ' ', s)
    return [w for w in s.split() if w]

def ngrams_absent(text, corpus, freq, n):
    """플래그 조건(노이즈 최소화): ① 구성 단어 전부 the author 어휘(freq≥1) AND ② 그중 ≥1개가
    *distinctive*(freq≤DISTINCT_MAX = the author 특징어, 예 '알맹이'=3) AND ③ 그 조합(n-gram) corpus 0건.
    = 'the author 특징어가 the author이 안 쓰던 이웃과 결합' = 봇 콜로케이션 신호. 흔한단어 조합·기술용어는 자동 배제."""
    ws = words(text)
    flagged, seen = [], set()
    for i in range(len(ws) - n + 1):
        win = ws[i:i+n]
        phrase = ' '.join(win)
        if phrase in seen:
            continue
        seen.add(phrase)
        norm = [strip_josa(w) for w in win]
        if not all(freq.get(w, 0) >= 1 for w in norm):     # ① 전부 the author 어휘
            continue
        if min(freq.get(w, 0) for w in norm) > DISTINCT_MAX:  # ② distinctive 단어 1개+ 포함
            continue
        variants = {phrase, ' '.join(win[:-1] + [strip_josa(win[-1])])}
        if not any(v in corpus for v in variants):          # ③ 조합 corpus 0건
            flagged.append(phrase)
    return flagged

def main():
    if len(sys.argv) < 2:
        sys.exit("사용: python3 check_corpus_phrases.py <draft.md> [--top N]")
    path = sys.argv[1]
    top = 40
    if '--top' in sys.argv:
        top = int(sys.argv[sys.argv.index('--top') + 1])
    corpus = load_corpus()
    freq = corpus_freq(corpus)
    body = draft_body(path)
    bi = ngrams_absent(body, corpus, freq, 2)
    tri = ngrams_absent(body, corpus, freq, 3)
    print(f"== corpus-phrase 리포트 (report-only) — {os.path.basename(path)} ==")
    print(f"   corpus {len(corpus):,}자 대조 · the author 발행본에 '0건'인 콜로케이션만 표시")
    print(f"   ⚠️ 이건 차단이 아니라 *검토 신호*. 기술용어·신규 고유표현은 정상일 수 있음.\n")
    print(f"-- 2-gram 미존재 {len(bi)}개 --")
    for p in bi[:top]:
        print(f"   • {p}")
    print(f"\n-- 3-gram 미존재 {len(tri)}개 (상위 {min(top,len(tri))}) --")
    for p in tri[:top]:
        print(f"   • {p}")
    print(f"\n[해석] 위 목록에 *말투/구어 콜로케이션*이 보이면(예: '진짜 알맹이') the author 표현 아닐 확률↑ → 차용 재확인.")

if __name__ == '__main__':
    main()
