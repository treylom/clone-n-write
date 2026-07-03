#!/usr/bin/env python3
"""band_scorer 스펙 — 스트레스 테스트에서 적출된 단점의 회귀 방지."""
import json
import os
import tempfile

import band_scorer as bs

# 합성 코퍼스: 초단문 행갈이 스타일 30편 (문장 8+개, 길이 80자+)
LINE = "짧게 쓴다\n그게 전부다\n오늘도 해봤다\n생각보다 어렵다\n그래도 계속한다\n결과는 나온다\n안되면 다시한다\n이게 방법이다"
CORPUS = [{'text': LINE + f"\n변형 {i}번째 기록이다\n숫자 {i}개 세어봤다"} for i in range(30)]


def _tmp_corpus():
    f = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False, encoding='utf-8')
    for d in CORPUS:
        f.write(json.dumps(d, ensure_ascii=False) + '\n')
    f.close()
    return f.name


def test_build_includes_self_dist():
    band = bs.build(_tmp_corpus())
    assert band['n_docs'] == 30
    assert len(band['self_score_dist']) == 30, "실글 자기점수 분포가 밴드에 저장돼야 함 (단점 1)"


def test_insufficient_sample_refuses_score():
    band = bs.build(_tmp_corpus())
    r = bs.score("두 문장뿐이다. 정말 짧다.", band)
    assert r['verdict'] == 'insufficient_sample', "8문장 미만이면 점수 대신 판정 불가 (단점 3)"
    assert 'raw' not in r


def test_percentile_and_calibration():
    band = bs.build(_tmp_corpus())
    r = bs.score(CORPUS[0]['text'], band)
    assert r['verdict'] == 'scored'
    assert r['percentile_vs_author'] is not None, "백분위 보고 (단점 1)"
    assert 'pass_hint' in r and 'over_typical' in r
    assert r['pass_hint'] is True, "코퍼스 자신의 글은 실글 p25 컷을 통과해야"


def test_caveat_always_present():
    band = bs.build(_tmp_corpus())
    r = bs.score(CORPUS[0]['text'], band)
    assert '단독 합격 판정 금지' in r['caveat'], "내용 무감 경고는 모든 출력에 (단점 2)"


def test_sparse_band_soft_penalty():
    # q_pct 대역이 [0,0,0]인 코퍼스 → 질문 1개짜리 글이 과잉 감점되지 않아야 (단점 5)
    band = bs.build(_tmp_corpus())
    band['bands']['q_pct'] = [0.0, 0.0, 0.0]
    with_q = CORPUS[0]['text'] + "\n이게 맞는 방법일까?"
    r = bs.score(with_q, band)
    assert r['per_metric']['q_pct']['score'] >= 60, "sparse 지표는 완만 감점"


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print(f"ok {name}")
    print("all green")
