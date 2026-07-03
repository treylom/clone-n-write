#!/usr/bin/env python3
"""
top_phrases.py — the author(the-author) 통합 corpus의 *유형별* 최빈 표현·어미·시그니처 통계.

배경(2026-07-02 persona-skill-rebuild Phase 1, orchestrator-bot dispatch / the author 핵심 지시):
  기존 유일 자동도구 check_corpus_phrases.py는 방향이 반대(*없는* 봇티 탐지)라
  "the author이 자주 쓰는 표현"을 surface 못 함 = positive-signal void(결함 c).
  → 본 도구는 *많이 쓰는* 표현을 유형별로 집계해 생성·채점의 positive-injection 소스로 쓴다.

🚨 유형별 집계 (the author: "어떤 글에선 많이, 어떤 글에선 적게 쓴다"):
  총 통계 ❌ → 글 유형별로 top-N 표현·어미 빈도표. 유형마다 목표 분포가 달라야 하므로.
  단, 장르 taxonomy(사색/정보/홍보/후기/에세이)는 Phase 2 type_profiler 몫 — Phase 1은
  *지금 확보되는 라벨*(source=threads/alookso/slide + 얼룩소 frontmatter category=주제)로 집계 시작.
  ⚠️ ceiling: category는 '주제'라 '장르' 근사일 뿐. genre 매핑 = Phase 2에서 이 통계 위에 얹음.

어미 분류는 check_endings.py PATTERNS/classify 재사용(정합). 형태소 근사 정규식, konlpy ❌.
입력: corpus/the-author-corpus.txt (build_corpus.py v2 산출 — `=== [src|label|date|ref] ===` 구분자)
출력: corpus/top-phrases-by-type.md (사람) + corpus/top-phrases-by-type.json (기계, schema_version+proof_class)
사용: python3 top_phrases.py [--top 15] [--min 3]
표준 라이브러리만.
"""
import os, re, sys, json
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_endings import classify, split_sentences  # noqa: E402  어미분류 SoT 재사용

CORPUS = os.path.join(HERE, "corpus", "the-author-corpus.txt")
OUT_MD = os.path.join(HERE, "corpus", "top-phrases-by-type.md")
OUT_JSON = os.path.join(HERE, "corpus", "top-phrases-by-type.json")

SEP = re.compile(r'^=== \[([^|]+)\|([^|]+)\|([^|]+)\|([^\]]+)\] ===$', re.M)

# 조사·어미 근사 제거(n-gram 정규화). check_corpus_phrases 정신 — 완벽 형태소 ❌, 노이즈 감축용.
JOSA = re.compile(r'(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만|까지|부터|께|한테|에게|이나|나|랑|이랑|보다|처럼|마다|조차|밖에)$')
# 시그니처 마커(문체 지문) — 밀도(per 10k자)로 리포트
SIG = {
    "해서,(문두 접속)": re.compile(r'(^|[.!?…]\s*)해서,'),
    "작은따옴표'…'": re.compile(r"'[^']{1,30}'"),
    "말줄임…/..": re.compile(r'(…|\.\.+)'),
    "ㅎㅎ/ㅋㅋ": re.compile(r'(ㅎ{2,}|ㅋ{2,})'),
    "~거든요": re.compile(r'거든요[.!?…)\s]'),
    "~구요/더라구요": re.compile(r'(구요|라구요|더라구요)[.!?…)\s]'),
    "~죠/~지요": re.compile(r'(죠|지요)[.!?…)\s]'),
}


def norm_token(w):
    w = re.sub(r'[^\w가-힣]', '', w)
    return JOSA.sub('', w)


def ngrams(text, n, min_len=2):
    toks = [norm_token(w) for w in text.split()]
    toks = [t for t in toks if len(t) >= min_len]
    return [' '.join(toks[i:i + n]) for i in range(len(toks) - n + 1)]


def load_docs():
    """corpus.txt → [(source,label,text)]. 구분자 기준 split."""
    raw = open(CORPUS, encoding='utf-8').read()
    docs = []
    marks = list(SEP.finditer(raw))
    for i, m in enumerate(marks):
        src, label = m.group(1).strip(), m.group(2).strip()
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(raw)
        docs.append((src, label, raw[start:end].strip()))
    return docs


def group_key(src, label):
    # slide는 source 단위로(본문/노트는 별도 label 유지). 나머지는 label(threads / 얼룩소 주제).
    return label if src != 'slide' else label


def analyze(texts, top, min_freq):
    joined = '\n'.join(texts)
    nchars = len(joined)
    # 어미 분포
    sents = split_sentences(joined)
    endc = Counter(classify(s) for s in sents if classify(s))
    total_s = sum(endc.values()) or 1
    endings = {k: round(endc.get(k, 0) / total_s * 100, 1)
               for k in ("평어단정", "합니다체", "해요체", "음슴체", "명사/기타")}
    # 시그니처 밀도(per 10k자)
    sig = {name: round(len(pat.findall(joined)) / (nchars / 10000 or 1), 1)
           for name, pat in SIG.items()}
    # 최빈 n-gram (2·3gram)
    phrases = {}
    for n in (2, 3):
        c = Counter(ngrams(joined, n))
        phrases[f"{n}gram"] = [[p, k] for p, k in c.most_common(top) if k >= min_freq]
    return {"docs": len(texts), "chars": nchars, "sentences": total_s,
            "endings_pct": endings, "signature_per10k": sig, "top_phrases": phrases}


def main():
    args = sys.argv[1:]
    top = int(args[args.index('--top') + 1]) if '--top' in args else 15
    min_freq = int(args[args.index('--min') + 1]) if '--min' in args else 3

    docs = load_docs()
    groups = defaultdict(list)
    for src, label, text in docs:
        groups[group_key(src, label)].append(text)

    report = {"schema_version": 1, "proof_class": "in-process",
              "note": "유형 라벨 = source/frontmatter category(주제) 근사. genre(사색/정보/홍보/후기/에세이) 매핑=Phase2 type_profiler. 어미분류=check_endings 재사용.",
              "params": {"top": top, "min_freq": min_freq},
              "groups": {}}
    # 편수 많은 그룹부터
    for key in sorted(groups, key=lambda k: -len(groups[k])):
        report["groups"][key] = analyze(groups[key], top, min_freq)

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 사람용 md
    lines = ["# the-author 유형별 최빈 표현·어미·시그니처 (top_phrases.py 산출)", "",
             f"> proof_class=in-process · 유형=source/주제 근사(genre=Phase2) · 어미=check_endings 재사용 · top{top}/min{min_freq}",
             ""]
    for key, g in report["groups"].items():
        lines.append(f"## {key} — {g['docs']}편 · {g['chars']:,}자 · 문장 {g['sentences']}")
        e = g['endings_pct']
        lines.append(f"- 어미%: 평어 {e['평어단정']} / 합니다 {e['합니다체']} / 해요 {e['해요체']} / 음슴 {e['음슴체']} / 명사·기타 {e['명사/기타']}")
        sg = g['signature_per10k']
        lines.append("- 시그니처(/10k자): " + " · ".join(f"{k} {v}" for k, v in sg.items()))
        for gram in ("2gram", "3gram"):
            top_list = g['top_phrases'][gram][:top]
            if top_list:
                lines.append(f"- 최빈 {gram}: " + ", ".join(f"{p}({k})" for p, k in top_list))
        lines.append("")
    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"✅ 유형별 통계 완료 → {OUT_MD}")
    print(f"   그룹 {len(report['groups'])}개: " + ", ".join(f"{k}({report['groups'][k]['docs']})" for k in report['groups']))
    print(f"   JSON → {OUT_JSON}")


if __name__ == '__main__':
    main()
