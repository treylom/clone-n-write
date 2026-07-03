# clone-n-write

**Clone how a real person thinks while writing — then use the same machinery to coach them to write better.**

Most "write in my style" prompts imitate word choice and die in the uncanny valley: the vocabulary matches, the *thinking* doesn't. clone-n-write goes after the process instead — how the author picks a direction, outlines by genre, borrows from their own published work while drafting, and self-edits — and verifies the surface style **with code, not vibes**, at the end.

```
 your published texts                        a new draft
        │                                         │
        ▼                                         ▼
 build_corpus.py ──▶ corpus + per-genre     type_profiler.py (genre?)
        │            stats (private,              │
        │            gitignored)                  ▼
        │                                 outline-playbooks.md
        │                                 (outline BEFORE prose — hard gate)
        │                                         │
        │                                         ▼
        └──────────▶ quant_scorer.py ◀── draft ──▶ rewrite_loop.py
                     (3-axis fingerprint,          (gold-anchored)
                      band + why + coach)                │
                                                         ▼
                                                      gate.py
                                          (4-axis pre-publish gate:
                                           endings · borrow-quotes ·
                                           provenance · AI-cliché tiers)
```

Two goals, in order:

1. **Imitate the thinking, not just the surface.** Most "style copy" prompts imitate word choice. This toolkit imitates the *writing process* — how the author picks a direction, outlines by genre, drafts by borrowing from their own published work, and self-edits — with the surface style (endings, rhythm, markers) verified at the end, by code.
2. **Coach, don't just clone.** Every measured target ships with a *why*. The scorer's output is not a number but a diagnosis: "your draft's sentence-length variance is 0.91; this genre's fingerprint is 0.55–0.72 — even out the breathing."

Built and used daily for one real author's Threads/longform output (that private corpus is **not** in this repo); published here as the generalized machinery.

## What coaching looks like

The scorer never says `72/100`. It reads the pack (per-genre fingerprint bands measured from the author's real corpus) and emits a diagnosis per metric:

```
[sentence-rhythm] your variance 0.91 · this genre's band 0.55–0.72
  why   : this author breathes in mid-length bursts; long-short whiplash reads as "assistant voice"
  coach : split the 3 longest sentences; keep one long sentence per paragraph at most

[question-ratio] your 0% · band 4–11%
  why   : rhetorical questions are how this author hands the topic to the reader
  coach : turn one flat assertion in the intro into a question
```

Band + why + coach, all generated from measured data — never from generic writing folklore.

## Real transformation examples

The [Korean README](README.md#실제-변환-예시--같은-글이-어떻게-바뀌나) shows the full end-to-end evidence in Korean: one neutral source text transformed into two different authors' voices (scored 89.3 and 89.5 against each author's measured fingerprint band, cross-scores dropping as expected), plus the actual rejection log where draft v1 failed the ending-distribution gate ("formal endings 54.5% vs author ceiling 30%") and converged after one round of coaching. The examples are pipeline outputs — no private corpus text is published.

## What's inside

| piece | what it does |
|---|---|
| `skill/outline-playbooks.md` | genre-typed outline templates + a hard "outline before prose" gate + 4-lens review (structural / reader / skeptic / voice) |
| `skill/gate.py` | pre-publish gate, 4 axes: ending-distribution guard (no assistant-voice flooding), borrow-quote check, base-provenance, **AI-cliché reverse detection** (two tiers: hard clichés that never appear in the author's corpus vs. capped ones that do) |
| `skill/build_corpus.py` | distills the author's published texts into a corpus + per-genre stats (you point it at your own sources) |
| `skill/type_profiler.py` | genre classification from ending-form distribution (stdlib only, no morphological analyzer) |
| `skill/quant_scorer.py` · `rewrite_loop.py` | quantitative 3-axis scoring + gold-anchored rewrite loop |
| `skill/connective_lib.py` | connective-tissue patterns (forward cues, pickups, bookends) with synthetic examples |
| `skill/check_endings.py` · `humanize_whitelist.py` · `check_corpus_phrases.py` | the smaller guards: ending counter, signature-protection during humanize passes, collocation-based bot-tell detection |
| `skill/multibot_judge.py` | multi-judge qualitative review prompt builder (fact-checker / reader-POV / style roles) |
| `skill/test_*.py` | runnable specs for all of the above (7 suites) |

Everything is Python stdlib. No API calls inside the toolkit itself — it's the deterministic layer around whatever model does the drafting.

## What you need to bring

This repo ships the **machinery, not the person**. To use it for a real persona you supply:

1. **A published corpus** — the author's actual published texts (not AI drafts). Point `build_corpus.py` at your sources; it emits `corpus/` (gitignored here).
2. **Genre profiles** — run the profiler over your corpus to calibrate per-genre ending distributions and style bands.
3. **Your names and paths** — placeholders like `PERSONA_VAULT_ROOT`, `BOT_AUTHOR_HINTS`, `<your-deck-dir>` mark every spot.

## Method notes (why it works)

- **Ending forms over word choice.** In Korean, sentence-ending forms (합니다체/해요체/평어/음슴체) are the strongest genre fingerprint — measured z-scores of +1.5 to +1.8 on a 1,000+ post corpus. Function-word and ending fingerprints are hard to consciously fake, which is exactly why they're good persona signals (the Burrows' Delta insight, applied to Korean).
- **Two-tier AI-cliché detection.** Naive "banned phrase" lists break persona fidelity: many alleged AI-tells actually appear in real human corpora. Tier 1 = phrases with **zero** occurrences in the author's corpus (hard fail). Tier 2 = phrases the author does use (allowed, frequency-capped). Build both tiers from *your* corpus, not from folklore.
- **Copy mode vs. universal mode.** Full-fidelity persona copying (`--mode copy`) tolerates the author's own quirks even where generic "good writing" advice wouldn't; `--mode universal` is the stricter general-purpose variant. Personal fidelity and universal polish are different objectives — pick one per run.
- **Outline first, always.** The single highest-leverage gate is refusing to draft before a genre-typed outline is approved. For new pieces the outline itself is built interactively (2–3 direction candidates → author picks → template-filled draft outline → author refines).

## Quickstart

```bash
cd skill
for t in test_*.py; do python3 "$t"; done   # 7 suites, all green, no corpus needed
```

Then wire your corpus (`build_corpus.py`), calibrate profiles, and put `gate.py` at the end of your drafting pipeline.

## License

MIT
