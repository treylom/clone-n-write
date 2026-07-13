#!/usr/bin/env python3
"""코퍼스 위생 게이트 테스트 — 2026-07 실측 오염(채널명/날짜 보일러플레이트 92%·근사 중복 8쌍) 재발 방지.

재현 시나리오: 크롤러가 남긴 채널명 줄과 날짜 줄이 대부분의 문서 선두에 붙고,
같은 글이 조회수 숫자만 달라진 채 두 번 캡처된 코퍼스.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_corpus import strip_cross_doc_boilerplate, drop_near_dups, clean_threads


def _doc(ref, text):
    return {'ref': ref, 'text': text}


def test_boilerplate_lines_stripped_when_repeated_across_docs():
    docs = [_doc(f'p{i}', f"Some Channel\n2026-03-{i+1:02d}\n본문 문장입니다 {i}. 두 번째 문장.") for i in range(10)]
    docs, boiler = strip_cross_doc_boilerplate(docs, ratio=0.2, min_docs=3)
    assert "Some Channel" in boiler, f"채널명 줄이 보일러플레이트로 검출돼야 함: {boiler}"
    for d in docs:
        assert "Some Channel" not in d['text']
    # 날짜 줄은 문서마다 달라 반복 검출 대상 아님 — clean_threads 정규식이 담당
    assert clean_threads("2026-03-09\n본문입니다.") == "본문입니다."


def test_unique_author_lines_survive():
    docs = [_doc('a', "Some Channel\n고유한 첫 문장.\n짧은 줄"), _doc('b', "Some Channel\n다른 고유 문장."),
            _doc('c', "Some Channel\n세 번째 글."), _doc('d', "Some Channel\n네 번째 글."), _doc('e', "Some Channel\n다섯째 글.")]
    docs, boiler = strip_cross_doc_boilerplate(docs, ratio=0.2, min_docs=3)
    assert "Some Channel" in boiler
    assert "짧은 줄" not in boiler, "1회만 나온 짧은 줄은 저자 산문일 수 있음 — 제거 금지"
    assert docs[0]['text'] == "고유한 첫 문장.\n짧은 줄"


def test_near_duplicate_docs_dropped():
    # 실측 조건 재현: 본문 500자급 동일 + 꼬리 숫자(조회수)만 다른 재캡처 쌍
    base = "실무에서 사용하는 도구 이야기. " * 30
    docs = [_doc('orig', base + "조회수 100"), _doc('recrawl', base + "조회수 999"), _doc('other', "완전히 다른 글. " * 40)]
    out, dropped = drop_near_dups(docs, prefix=200)
    assert len(out) == 2 and dropped == ['recrawl'], f"근사 중복 1편이 드롭돼야 함: {dropped}"


def test_exact_short_docs_not_falsely_dropped():
    docs = [_doc('a', "짧은 글 하나."), _doc('b', "짧은 글 둘.")]
    out, dropped = drop_near_dups(docs)
    assert len(out) == 2 and not dropped


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            try:
                fn()
                print(f"✅ {name}")
            except AssertionError as e:
                fails += 1
                print(f"❌ {name}: {e}")
    sys.exit(1 if fails else 0)
