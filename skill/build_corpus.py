#!/usr/bin/env python3
"""
build_corpus.py — the author(the-author) authoritative 글 corpus 통합 빌더 (v2 — provenance+dedup+pptx).

배경(2026-06-30 hard-gate 회의): 기존 corpus 단정이 data-analysis-547.jsonl(=Threads-only)만
봐서 얼룩소 어휘를 '0건→봇표현'으로 오판('알맹이' 사건). → Threads + 얼룩소를 합친 *통합 corpus*가
phrase detector(check_corpus_phrases.py)의 정확도 선결.

v2 확장 (2026-07-02 persona-skill-rebuild Phase 1, orchestrator-bot dispatch):
  - 편별 provenance 구분자(`=== [source | label | date | ref] ===`) — 예제기반 재조립의
    "the author 실제 글 3~5편 통째 차용"이 편 경계를 요구. 기존 raw dump(구분자 0) 해소.
  - dedup: 동일 본문(sha1) 중복 제거 — 기존 corpus에 동일 블록 반복 확인됨.
  - pptx 핸들러: 강의 덱(선택 소스) 슬라이드 본문 + 발표자 노트 흡수
    (brand chrome 필터·HTML 엔티티 디코드·notes 별도). zipfile stdlib만(python-pptx ❌).
  - 구조화 인덱스 corpus/corpus-index.jsonl(편별 source·label·date·chars·sha1) — top_phrases.py 소비.

출력:
  corpus/the-author-corpus.txt   (구분자 포함 정규화 텍스트, 사람 검수 가능 · check_corpus_phrases 계약 보존)
  corpus/corpus-index.jsonl     (편별 메타 1줄씩)
사용: python3 build_corpus.py   (스킬 폴더에서)
표준 라이브러리만.
"""
import json, os, re, sys, glob, zipfile, html, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.environ.get("PERSONA_VAULT_ROOT", ".")
JSONL = os.path.join(VAULT, "<notes-tree>/meetings/2026-06-13-the-author-persona-reset/data-analysis-547.jsonl")
EOLLUKSO_DIRS = [
    os.path.join(VAULT, "<notes-tree>/<longform-dir>"),
]
# 최종 강의 덱만(중간 draft·raw·v2~v4 제외). 없는 경로는 skip(존재 가드) — 재현성 위해 존재 여부 로그.
SLIDE_GLOBS = [
    # git-추적 vault 정본(Part2 클립 최종본)
    os.path.join(VAULT, "<your-deck-dir>/*.pptx"),
    # 세미나 통짜 덱 최종본
    os.path.join(VAULT, "<your-deck-dir>/deck-example-1.pptx"),
    os.path.join(VAULT, "<your-deck-dir>/deck-example-2.pptx"),
    # 홈 최종 산출(Part1/2/3 클립 — git 밖, 존재 시 흡수)
    os.path.expanduser("~/your-extra-source-dir/deliver/*.pptx"),
    os.path.expanduser("~/your-extra-source-dir/part3-deliver-v4/*.pptx"),
]
OUT_DIR = os.path.join(HERE, "corpus")
OUT = os.path.join(OUT_DIR, "the-author-corpus.txt")
INDEX = os.path.join(OUT_DIR, "corpus-index.jsonl")

# 슬라이드 brand chrome(문체 아님) 필터. ceiling: 정규식 근사 — 완벽 필터 아님, 대부분의 라벨·로고 제거.
CHROME = re.compile(
    r"^\s*(PART\s|CLIP\s|Part\s|Clip\s|·\s*CLIP|YourBrand|YOURBRAND|당신의브랜드"
    r"|PART\s*\d|\d+\.\d+(\.\d+)?\s*$|©|™)"
)


def strip_md(t):
    t = re.sub(r'^---\n.*?\n---\n', '', t, flags=re.S)          # frontmatter
    t = re.sub(r'`{1,3}[^`]*`{1,3}', ' ', t)                    # code
    t = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', t)            # links/img
    t = re.sub(r'^[#>\-\*\|]+', ' ', t, flags=re.M)             # md marks
    t = re.sub(r'\*\*|\*|__|~~', '', t)
    return t


def dedup_lines(t, min_len=20):
    """문서 내 반복(스크래퍼가 본문을 2중 복제) 제거 — 실질 라인(≥min_len)만 dedup, 짧은 접속어는 보존."""
    seen, out = set(), []
    for ln in t.splitlines():
        s = ln.strip()
        if len(s) >= min_len:
            key = re.sub(r'\s+', '', s)
            if key in seen:
                continue
            seen.add(key)
        out.append(ln)
    return '\n'.join(out)


# 얼룩소 boilerplate (the author 목소리 아님 — 반드시 제거): AI 기계요약·bio·카운트·footer
ALOOKSO_BIO = re.compile(r'인공지능,?\s*정치과정.*?연구활동가\(Activist Researcher\)입니다\.?[^\n]*', re.S)
# Threads 스크래퍼 UI chrome — 이 마커부터 절단
THREADS_CHROME = re.compile(r'\n\s*(Translate|Top|View activity|Reply to|No replies|replies yet|Repost|Quote|더 보기)\b')


def clean_threads(t):
    t = THREADS_CHROME.split(t, maxsplit=1)[0]         # UI chrome 이후 절단
    t = re.sub(r'^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$', '', t, flags=re.M)   # MM/DD/YY 날짜 스탬프
    t = re.sub(r'^\s*@\w+\s*$', '', t, flags=re.M)     # @핸들 단독 줄
    return dedup_lines(t).strip()


def clean_alookso(raw):
    t = re.sub(r'^---\n.*?\n---\n', '', raw, flags=re.S)               # frontmatter
    t = re.split(r'\n#{1,6}\s*관련 노트', t)[0]                          # 관련노트 footer 이후 통째
    t = re.split(r'←\s*\[\[', t)[0]                                    # nav footer
    t = re.sub(r'AI 요약:.*?(?=\n\s*\n|\npublished:|\n글 전문:)', '', t, flags=re.S)  # 🚨 기계 요약(AI 문체)
    t = re.sub(r'^\s*키워드:.*$', '', t, flags=re.M)
    t = re.sub(r'^\s*published:.*$', '', t, flags=re.M)
    t = re.sub(r'^\s*글 전문:.*$', '', t, flags=re.M)
    t = ALOOKSO_BIO.sub('', t)                                         # bio 블록
    t = re.sub(r'\*{0,2}AUTHOR_BYLINE_PATTERN\*{0,2}', '', t)
    t = re.sub(r'^\s*(글|팔로워|팔로잉|북마크|원글|경제/\S+)\s*\*{0,2}[\d.,KM]*\*{0,2}\s*$', '', t, flags=re.M)
    t = re.sub(r'^\s*\d[\d.,KM]*\s*$', '', t, flags=re.M)              # 잔여 카운트 숫자
    t = strip_md(t)
    return dedup_lines(t).strip()


def a_t_runs(xml_bytes):
    """pptx slide/notes XML에서 <a:t> 텍스트 런 추출 + HTML 엔티티 디코드."""
    xml = xml_bytes.decode('utf-8', 'ignore')
    return [html.unescape(r) for r in re.findall(r'<a:t>(.*?)</a:t>', xml, re.S)]


def pptx_text(path):
    """덱 슬라이드 본문(chrome 필터) + 발표자 노트. (body_text, notes_text) 반환."""
    z = zipfile.ZipFile(path)
    body, notes = [], []
    for name in z.namelist():
        if re.match(r'ppt/slides/slide\d+\.xml$', name):
            for r in a_t_runs(z.read(name)):
                r = r.strip()
                if r and not CHROME.match(r):
                    body.append(r)
        elif re.match(r'ppt/notesSlides/notesSlide\d+\.xml$', name):
            for r in a_t_runs(z.read(name)):
                r = r.strip()
                if r and not CHROME.match(r) and not r.isdigit():
                    notes.append(r)
    return ' '.join(body), '\n'.join(notes)


def fm_field(raw, key):
    """frontmatter 단일 필드 값(따옴표 제거). 없으면 ''."""
    m = re.search(rf'^{key}:\s*"?([^"\n]+)"?', raw, re.M)
    return m.group(1).strip() if m else ''


def collect():
    """편별 doc 리스트 반환. doc = {source, label, ref, date, text}."""
    docs, stats = [], {'jsonl_threads': 0, 'eollukso_md': 0,
                       'slide_decks': 0, 'slide_missing_globs': 0}

    # 1) Threads jsonl — the author own fields only (full_own 우선, 없으면 body)
    if os.path.exists(JSONL):
        with open(JSONL, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                for k in ('full_own', 'body'):
                    v = d.get(k)
                    if isinstance(v, str) and v.strip():
                        cleaned = clean_threads(v)
                        if not cleaned:
                            break
                        url = str(d.get('url', ''))
                        docs.append({
                            'source': 'threads', 'label': 'threads',
                            'ref': url.rsplit('/', 1)[-1] or url,
                            'date': str(d.get('dt', '')), 'text': cleaned,
                        })
                        stats['jsonl_threads'] += 1
                        break

    # 2) 얼룩소 essays — label = frontmatter category(주제) or 폴더명. (장르=Phase2 type_profiler)
    for base in EOLLUKSO_DIRS:
        for p in glob.glob(os.path.join(base, '**', '*.md'), recursive=True):
            if '/worktree' in p or '.worktrees' in p:
                continue
            fn = os.path.basename(p)
            if 'MOC' in fn or '작업과정' in fn:
                continue
            try:
                raw = open(p, encoding='utf-8').read()
            except Exception:
                continue
            label = fm_field(raw, 'category') or os.path.basename(os.path.dirname(p))
            date = fm_field(raw, 'created') or fm_field(raw, 'published')
            docs.append({
                'source': 'alookso', 'label': label,
                'ref': fn, 'date': date, 'text': clean_alookso(raw),
            })
            stats['eollukso_md'] += 1

    # 3) 강의 덱(선택 소스) — 슬라이드 본문 + 발표자 노트
    seen_deck = set()
    for pattern in SLIDE_GLOBS:
        hits = glob.glob(pattern)
        if not hits:
            stats['slide_missing_globs'] += 1
            continue
        for path in hits:
            ref = os.path.basename(path)
            if ref in seen_deck:
                continue
            seen_deck.add(ref)
            try:
                body, notes = pptx_text(path)
            except Exception:
                continue
            # 본문(라벨형 단문)과 노트(산문) 분리 라벨 — 문체 신호는 노트가 더 값짐
            if body.strip():
                docs.append({'source': 'slide', 'label': 'slide-body',
                             'ref': ref, 'date': '', 'text': body})
            if notes.strip():
                docs.append({'source': 'slide', 'label': 'slide-notes',
                             'ref': ref, 'date': '', 'text': notes})
            stats['slide_decks'] += 1

    return docs, stats


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    docs, stats = collect()

    # dedup: 동일 본문(정규화 후 sha1) 제거
    seen, uniq, dup = set(), [], 0
    for d in docs:
        h = hashlib.sha1(re.sub(r'\s+', ' ', d['text']).strip().encode('utf-8')).hexdigest()
        if h in seen:
            dup += 1
            continue
        seen.add(h)
        d['sha1'] = h
        uniq.append(d)

    # corpus.txt: 편별 provenance 구분자 + 본문 (check_corpus_phrases 통짜-read 계약 보존)
    parts, index = [], []
    for d in uniq:
        sep = f"=== [{d['source']} | {d['label']} | {d['date'] or '-'} | {d['ref']}] ==="
        parts.append(sep + "\n" + d['text'].strip())
        index.append({'source': d['source'], 'label': d['label'], 'ref': d['ref'],
                      'date': d['date'], 'chars': len(d['text']), 'sha1': d['sha1']})
    text = '\n\n'.join(parts)

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(text)
    with open(INDEX, 'w', encoding='utf-8') as f:
        for row in index:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"✅ corpus 빌드 완료(v2) → {OUT}")
    print(f"   소스: Threads {stats['jsonl_threads']}편 + 얼룩소 {stats['eollukso_md']}편 "
          f"+ 슬라이드덱 {stats['slide_decks']}개(missing globs {stats['slide_missing_globs']})")
    print(f"   dedup: 중복 {dup}편 제거 → 고유 {len(uniq)}편")
    print(f"   총 {len(text):,}자 · 인덱스 → {INDEX}")
    # 검증 샘플
    for probe in ('알맹이', '진짜 알맹이', '껍데기'):
        print(f"   probe '{probe}': {text.count(probe)}회")


if __name__ == '__main__':
    main()
