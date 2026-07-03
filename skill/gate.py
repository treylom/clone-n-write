#!/usr/bin/env python3
"""
gate.py — 저자 글 발신 전 통합 게이트.

설계 배경: 스킬 *호출은 됐는데* 핵심 step(저자 실제 글 차용)을 스킵하고 봇 중간초안을
base로 오인 → 봇표현 잔존. 게이트의 본질 = **"authoritative corpus grounding 강제"**.

3축(robust 순):
  🥇 base-provenance : base가 the author 발행본(author:the-author·발행경로·블록마커 없음)인가. 봇 draft base=FAIL.
                       — base만 맞으면 voice 자동 정합(blocklist 불필요). root cause 직격.
  🥈 borrow-evidence : 드래프트가 the author 실제 글을 file:line으로 ≥1 인용(차용 실행 흔적).
  🥉 corpus-phrase   : check_corpus_phrases 의 distinctive 0-gram(예 '진짜 알맹이'). **advisory**
                       (한글 형태소 노이즈+stdlib 한계로 pass 차단 ❌, 사람 검토 신호로만).

출력(orchestrator-bot Stop-gate hook 계약): <draft>.tofugate.json
  {base_path, base_author, base_ok, borrow_quotes:[…], corpus_flags:[…], pass:bool, schema_version, proof_class, ts}
PASS = base_ok ∧ len(borrow_quotes)≥1.   (corpus_flags=advisory, pass 비차단)

사용: python3 gate.py <draft.md> [--ts ISO]
표준 라이브러리만. 선행: build_corpus.py.
"""
import json, os, re, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

PUBLISHED_PATH_HINTS = ('threads', '-published', 'longform')  # path fragments marking published corpus files
BOT_AUTHOR_HINTS = ('bot', 'assistant', 'agent')  # fill with your own bot/agent names

# ── 4축: AI 상투구 역탐지 (two-tier, built from the author corpus) ──
# 등급은 the author 코퍼스(N.NM chars (measure your own corpus)) 실측으로 분류 — 통짜 하드컷은 the author 보이스와 충돌(예: '안녕하세요' 142회).
# HARD  = 코퍼스 출현 0 → 1회라도 나오면 FAIL (the author이 안 쓰는 순수 AI 상투구)
# ADV   = 코퍼스 출현 있음 → 빈도비 판정: 드래프트 1k자당 비율이 코퍼스 대비 과다 + 종류 다수일 때만
AI_TELLS_HARD = ("도움이 되셨다면", "놓치지 마세요", "함께 살펴보", "에 대해 알아보")
AI_TELLS_ADV = ("이번 글에서는", "이 글에서는", "알아보겠습니다", "살펴보겠습니다", "결론적으로",
                "요약하자면", "다음과 같습니다", "궁극적으로", "시사합니다", "첫째", "둘째", "마무리하며")
AI_ADV_DISTINCT_FAIL = 3   # 서로 다른 ADV 상투구 3종+ = AI 결
AI_ADV_REPEAT_FAIL = 3     # 같은 ADV 상투구 3회+ 반복 = AI 결

def ai_tells_check(body, mode):
    """returns (ok, hard_hits, adv_hits, note). mode=copy(개인 완전복사)면 ADV축은 경고만."""
    hard = [t for t in AI_TELLS_HARD if t in body]
    adv = {t: body.count(t) for t in AI_TELLS_ADV if t in body}
    adv_fail = (len(adv) >= AI_ADV_DISTINCT_FAIL) or any(c >= AI_ADV_REPEAT_FAIL for c in adv.values())
    if mode == 'copy':
        ok = not hard  # 개인 완전복사(copy): 저자도 쓰는 표현(ADV)은 완성도 깎여도 유지(author policy)
        note = "copy 모드 — ADV 상투구는 보이스 일부로 허용(경고만), HARD(the author 무사용)만 차단"
    else:
        ok = (not hard) and (not adv_fail)
        note = f"universal 모드 — HARD 0건 AND ADV(종류<{AI_ADV_DISTINCT_FAIL}·반복<{AI_ADV_REPEAT_FAIL}) 요구"
    return ok, hard, adv, note

def read(path):
    return open(path, encoding='utf-8').read()

def frontmatter(text):
    m = re.match(r'^---\n(.*?)\n---\n', text, flags=re.S)
    return m.group(1) if m else ''

def fm_field(fm, *names):
    for nm in names:
        m = re.search(rf'^\s*{re.escape(nm)}\s*:\s*(.+)$', fm, flags=re.M)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return ''

def has_block_markers(text):
    # 봇 draft 특유 이어쓰기 블록마커
    return bool(re.search(r'\*\*[①-⑮]\*\*', text)) or len(re.findall(r'^\s*\*\*\d+\*\*', text, flags=re.M)) >= 3


def detect_media(draft_text, draft_path):
    """글 매체 판정 — 얼룩소 자동 게이트 확장(결함 a). Threads 전용 → 얼룩소도 gate.

    우선순위: frontmatter platform(AlookSo) → Threads 블록마커 → 경로(/얼룩소/) → 기본 threads.
    """
    fm = frontmatter(draft_text)
    platform = fm_field(fm, 'platform', '플랫폼', '매체').lower()
    if 'alookso' in platform or '얼룩소' in platform:
        return 'alookso'
    if has_block_markers(draft_text):
        return 'threads'
    low = draft_path.lower()
    if '얼룩소' in low or 'longform' in low or '/essays' in low or '/essay' in low:
        return 'alookso'
    return 'threads'


def keep_collocation(flag):
    """collocation 단위 AI티만 유지(결함 a): 단일 단어 flag 드롭 → word 오탐 제거.

    '알맹이'(word) 오탐 ❌ / '진짜 알맹이'(collocation) 유지 ✅.
    2+토큰 조합만 advisory 로 남긴다(형태소 노이즈는 여전히 advisory·비차단).
    """
    return len(flag.split()) >= 2

def resolve_base(draft_text, draft_path):
    """드래프트 frontmatter의 base/베이스 선언에서 base 파일 경로 추출."""
    fm = frontmatter(draft_text)
    raw = fm_field(fm, '베이스', 'base', 'baseline', '차용 baseline')
    # `path` 형태 또는 경로 토큰 추출
    m = re.search(r'`([^`]+\.(?:md|txt))`', raw) or re.search(r'([\w./\-가-힣]+\.(?:md|txt))', raw)
    return (m.group(1) if m else ''), raw

def find_base_file(token):
    if not token:
        return ''
    if os.path.isabs(token) and os.path.exists(token):
        return token
    VAULT = os.environ.get("PERSONA_VAULT_ROOT", ".")
    # 직접 결합
    for root in (VAULT, os.path.join(VAULT, "<notes-tree>"), os.path.expanduser("~/.claude/your-drafts-dir")):
        cand = os.path.join(root, token)
        if os.path.exists(cand):
            return cand
    # basename 검색
    base = os.path.basename(token)
    try:
        out = subprocess.run(["find", VAULT, os.path.expanduser("~/.claude/your-drafts-dir"),
                              "-name", base, "-not", "-path", "*worktree*"],
                             capture_output=True, text=True, timeout=20).stdout.split('\n')
        for p in out:
            if p.strip():
                return p.strip()
    except Exception:
        pass
    return ''

def base_provenance(base_token, base_raw):
    base_file = find_base_file(base_token)
    if not base_file:
        return '', 'UNKNOWN', False, f"base 파일 못 찾음(token={base_token!r})"
    txt = read(base_file)
    author = fm_field(frontmatter(txt), 'author', '작성자') or 'UNKNOWN'
    low_path = base_file.lower()
    blockish = has_block_markers(txt)
    author_is_bot = any(h in author.lower() for h in BOT_AUTHOR_HINTS)
    author_is_tofu = 'the-author' in author.lower() or '재경' in author and not author_is_bot
    path_published = any(h in low_path for h in PUBLISHED_PATH_HINTS)
    # base_ok: the author 발행본 신호(author the-author 또는 발행경로) AND 봇 블록마커 아님
    ok = (author_is_tofu or (path_published and not author_is_bot)) and not blockish
    why = f"author={author} path_published={path_published} blockmarkers={blockish} author_is_bot={author_is_bot}"
    return base_file, author, ok, why

def borrow_quotes(draft_text):
    """차용 evidence = frontmatter/본문의 file:line 인용 또는 차용 출처 선언."""
    quotes = []
    # file.md:123 또는 `file`:L12 패턴
    for m in re.finditer(r'([\w./\-가-힣]+\.(?:md|txt|jsonl))\s*[:：]\s*L?(\d+)', draft_text):
        quotes.append(f"{m.group(1)}:{m.group(2)}")
    # 차용/baseline/출처 선언 라인(파일명 포함)
    for m in re.finditer(r'^.*?(?:차용|borrow|출처|샘플).*?`([^`]+\.(?:md|txt|jsonl))`.*$', draft_text, flags=re.M):
        quotes.append(m.group(1))
    return sorted(set(quotes))

def corpus_flags(draft_path):
    script = os.path.join(HERE, "check_corpus_phrases.py")
    if not os.path.exists(script):
        return ['(check_corpus_phrases.py 없음)']
    try:
        out = subprocess.run([sys.executable, script, draft_path, "--top", "60"],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception as e:
        return [f"(detector 실행 실패: {e})"]
    flags = re.findall(r'^\s*•\s*(.+)$', out, flags=re.M)
    # advisory: collocation(2+토큰)만 — 단일 단어 오탐 제거(결함 a). 상위 일부.
    flags = [f for f in flags if keep_collocation(f)]
    return flags[:40]

def main():
    if len(sys.argv) < 2:
        sys.exit("사용: python3 gate.py <draft.md> [--ts ISO]")
    path = os.path.abspath(sys.argv[1])
    ts = sys.argv[sys.argv.index('--ts')+1] if '--ts' in sys.argv else 'UNSET'
    mode = sys.argv[sys.argv.index('--mode')+1] if '--mode' in sys.argv else 'copy'
    draft = read(path)

    base_token, base_raw = resolve_base(draft, path)
    base_file, base_author, base_ok, why = base_provenance(base_token, base_raw)
    quotes = borrow_quotes(draft)
    flags = corpus_flags(path)
    media = detect_media(draft, path)
    # 4축: frontmatter 제외한 본문만 검사 (인용·차용 표기 오탐 방지)
    body = re.sub(r'^---\n.*?\n---\n', '', draft, flags=re.S)
    ai_ok, ai_hard, ai_adv, ai_note = ai_tells_check(body, mode)
    passed = bool(base_ok and len(quotes) >= 1 and ai_ok)

    report = {
        "schema_version": 1,
        "proof_class": "in-process",
        "draft": path,
        "media": media,
        "base_path": base_file,
        "base_token": base_token,
        "base_author": base_author,
        "base_ok": base_ok,
        "base_why": why,
        "borrow_quotes": quotes,
        "corpus_flags": flags,
        "corpus_flags_note": "advisory only — 한글 형태소 노이즈로 pass 비차단. 말투 콜로케이션('진짜 알맹이' 류) 육안 검토 신호.",
        "mode": mode,
        "ai_tells_ok": ai_ok,
        "ai_tells_hard": ai_hard,
        "ai_tells_adv": ai_adv,
        "ai_tells_note": ai_note,
        "pass": passed,
        "pass_rule": "base_ok AND borrow_quotes>=1 AND ai_tells_ok (corpus_flags advisory)",
        "ts": ts,
    }
    out_path = path + ".tofugate.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"== the-author 발신 게이트 — {os.path.basename(path)} [매체:{media}] ==")
    print(f"🥇 base-provenance : {'✅ OK' if base_ok else '❌ FAIL'}  (base={os.path.basename(base_file) or '?'}, author={base_author})")
    print(f"     why: {why}")
    print(f"🥈 borrow-evidence : {'✅' if quotes else '❌'} {len(quotes)}건  {quotes[:4]}")
    print(f"🥉 corpus-phrase   : {len(flags)} advisory flags (비차단) — 말투 콜로케이션 보이면 차용 재확인")
    print(f"4️⃣ ai-tells [{mode}] : {'✅ OK' if ai_ok else '❌ FAIL'}  hard={ai_hard} adv={ai_adv}")
    print(f"     {ai_note}")
    susp = [f for f in flags if '진짜' in f or '알맹이' in f]
    if susp:
        print(f"     ⚠️ 의심 콜로케이션: {susp[:6]}")
    print(f"\n{'🟢 PASS' if passed else '🔴 FAIL'} — {report['pass_rule']}")
    print(f"→ {out_path}")
    # orchestrator-bot Stop-gate hook 인식용 마커 (transcript stdout) — 파일만 쓰면 hook이 못 봄
    print(f"tofugate: {json.dumps({'pass': passed, 'base_ok': base_ok, 'borrow': len(quotes), 'draft': os.path.basename(path)}, ensure_ascii=False)}")
    sys.exit(0 if passed else 2)

if __name__ == '__main__':
    main()
