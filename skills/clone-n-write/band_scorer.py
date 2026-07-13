#!/usr/bin/env python3
"""band_scorer.py — 코퍼스 대역(밴드) 기반 문체 지문 채점기.

2026-07 스트레스 테스트에서 적출된 단점을 반영한 설계:
  1) 절대점수의 함정 — 저자 실글도 절반이 '대역 중앙'에서 떨어져 있다.
     → raw 점수와 함께 **저자 실글 분포 백분위(percentile)** 를 반환하고,
       합격 컷은 실글 분포에서 캘리브레이션한다 (calibrate()).
     → 실글 p90 초과 전형성은 over_typical 경고 (저자보다 저자다움 = AI 신호).
  2) 표본 부족 — 문장 수가 적으면 분포 지표가 무의미.
     → MIN_SENTS 미만이면 점수 대신 verdict="insufficient_sample" 반환.
  3) sparse 지표 — 과반 문서가 0인 지표(질문율 등)는 p50=0이라 거리가 왜곡.
     → 대역이 [0, 0, x] 꼴이면 usage/강도 2단으로 완화 채점.
  4) 장르-저자 얽힘 — 전장르 밴드는 '저자×주류장르'를 잰다.
     → 밴드 파일을 장르별로 받는 것을 1급 사용법으로 문서화 (사용자 책임).

주의: 이 점수는 표면 지문만 잰다 — 내용 무감(게이밍 취약).
정성 심사(4렌즈 리뷰·multibot_judge)와 합성 없이 단독 합격 판정에 쓰지 말 것.

사용:
  python3 band_scorer.py build  <corpus.jsonl> <band.json>       # 밴드 + 실글 점수 분포 캘리브레이션
  python3 band_scorer.py score  <draft.txt>    <band.json>       # 채점 (JSON 출력)
corpus.jsonl: {"text": "..."} 한 줄당 한 문서.
"""
import json
import re
import sys

MIN_SENTS = 8          # 이 미만이면 판정 불가 (단점 3)
SPARSE_ZERO_BAND = 1e-9

# ── 문장·지표 ────────────────────────────────────────────────

def split_sentences(t):
    s = re.split(r'(?<=[.!?…])\s+|\n+', t)
    return [x.strip() for x in s if x.strip() and len(x.strip()) > 1]

END_FORMAL = re.compile(r'(습니다|합니다|입니다|됩니다|십시오)[.!?…]*$')
END_POLITE = re.compile(r'([에예어아해져와봐줘가나끄]요|죠|네요|세요|는데요|거든요|더라고요|랍니다)[.!?…]*$')
END_PLAIN = re.compile(r'(이다|한다|었다|았다|겠다|다)[.!?…]*$')


def metrics(t):
    sents = split_sentences(t)
    n = len(sents) or 1
    lens = [len(s.split()) for s in sents] or [0]
    mean = sum(lens) / len(lens)
    var = sum((l - mean) ** 2 for l in lens) / len(lens)
    ends = {'formal': 0, 'polite': 0, 'plain': 0, 'clipped': 0}
    for s in sents:
        if END_FORMAL.search(s):
            ends['formal'] += 1
        elif END_POLITE.search(s):
            ends['polite'] += 1
        elif END_PLAIN.search(s):
            ends['plain'] += 1
        else:
            ends['clipped'] += 1          # 명사·구 종결, 행갈이 조각
    return {
        'n_sents': n,
        'mean_words': round(mean, 2),
        'cv': round((var ** 0.5) / mean, 3) if mean else 0.0,
        'q_pct': round(100 * sum('?' in s for s in sents) / n, 1),
        'ends_formal': round(100 * ends['formal'] / n, 1),
        'ends_polite': round(100 * ends['polite'] / n, 1),
        'ends_clipped': round(100 * ends['clipped'] / n, 1),
    }

METRIC_KEYS = ['mean_words', 'cv', 'q_pct', 'ends_formal', 'ends_polite', 'ends_clipped']

# ── 채점 ────────────────────────────────────────────────────

def _quantiles(vals):
    v = sorted(vals)
    n = len(v)
    return [v[n // 4], v[n // 2], v[3 * n // 4]]


def metric_score(v, lo, med, hi):
    """대역 중앙 거리 기반: d=0 → 100, 경계 d=1 → 90, 밖은 -30/단위."""
    if hi - lo < SPARSE_ZERO_BAND and med < SPARSE_ZERO_BAND:
        # sparse 지표 (단점 5): 대역이 사실상 0 — 사용량만 완만 감점
        return max(0.0, 100 - 3 * v), None
    half = max((hi - lo) / 2, 1e-6)
    d = abs(v - med) / half
    s = 100 - 10 * d if d <= 1 else 90 - 30 * (d - 1)
    return max(0.0, round(s, 1)), round(d, 2)


def raw_score(text, band):
    m = metrics(text)
    per = {}
    total = 0.0
    for k in METRIC_KEYS:
        lo, med, hi = band['bands'][k]
        s, d = metric_score(m[k], lo, med, hi)
        per[k] = {'value': m[k], 'score': s, 'd': d, 'band': [lo, med, hi]}
        total += s
    return round(total / len(METRIC_KEYS), 1), m, per


def percentile(x, dist):
    if not dist:
        return None
    return round(100 * sum(1 for v in dist if v <= x) / len(dist), 1)


def score(text, band):
    m = metrics(text)
    if m['n_sents'] < MIN_SENTS:
        return {'verdict': 'insufficient_sample',
                'why': f"문장 {m['n_sents']}개 < 최소 {MIN_SENTS} — 분포 지표가 무의미해 점수를 내지 않음"}
    raw, m, per = raw_score(text, band)
    dist = band.get('self_score_dist', [])
    pct = percentile(raw, dist)
    out = {'verdict': 'scored', 'raw': raw, 'percentile_vs_author': pct,
           'per_metric': per,
           'caveat': '표면 지문만 잰다 — 정성 심사와 합성 없이 단독 합격 판정 금지'}
    if dist:
        p25 = _quantiles(dist)[0]
        p90 = sorted(dist)[int(len(dist) * 0.9)]
        out['pass_hint'] = raw >= p25
        out['over_typical'] = raw > p90
        out['calibration'] = {'author_p25': p25, 'author_p90': round(p90, 1)}
    return out

# ── 밴드 구축 (실글 분포 캘리브레이션 포함) ──────────────────

def build(corpus_path):
    docs = [json.loads(l)['text'] for l in open(corpus_path, encoding='utf-8') if l.strip()]
    docs = [d for d in docs if len(d) >= 80]
    ms = [metrics(d) for d in docs]
    band = {'n_docs': len(docs),
            'bands': {k: _quantiles([m[k] for m in ms]) for k in METRIC_KEYS}}
    # 실글 자기점수 분포 = 합격 컷·백분위의 기준 (단점 1)
    band['self_score_dist'] = sorted(raw_score(d, band)[0] for d in docs)
    return band


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    cmd, a, b = sys.argv[1], sys.argv[2], sys.argv[3]
    if cmd == 'build':
        band = build(a)
        json.dump(band, open(b, 'w', encoding='utf-8'), ensure_ascii=False)
        dist = band['self_score_dist']
        print(f"band written: {b} (docs={band['n_docs']}, author self-score p50={dist[len(dist)//2]})")
    elif cmd == 'score':
        band = json.load(open(b, encoding='utf-8'))
        print(json.dumps(score(open(a, encoding='utf-8').read(), band), ensure_ascii=False, indent=1))
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
