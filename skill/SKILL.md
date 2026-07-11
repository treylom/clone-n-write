---
name: clone-n-write
description: Use when drafting or reworking posts in a specific person's voice AND structure. Onboarding interview + graded exemplar registry + skeleton-anchored outlines + non-compensatory style/structure diagnostics + blind A/B harness.
version: 2.1.1
---

# clone-n-write v2 (generalized template)

> **Mission**: reproduce how a real person *thinks while writing* — message → outline → draft → self-edit — including the **structure** of their pieces (openings, paragraph rhythm, transitions, closings), not just surface style. Every gate and number is a means, never a mechanical mandate.

> Generalized public template. All persona data lives under `personas/<name>/` (never ship a real person's data in public forks). Calibrate every number against **your** author's corpus.

## Step 0 — Onboarding interview (once per persona)

Ask the author ~8 questions and persist to `personas/<name>/author-interview.md` (+ `.json` mirror for tools):
thinking origin (message-first? scene-first?) / "what feels off" signals / seed pieces they consider their best (with why) / medium→structure mapping / appeal of the clone target in 3 axes / noise criteria / must-keep & never-use expressions / imagined reader.
Every writing session loads this file first; hosts that persist context re-inject it at session start. The interview is the author's *tacit knowledge* — treat it as spec, not decoration.

## Data layer — exemplar registry (not a flat corpus)

`registry.py {build,pull,add,resplit,stats}` maintains `personas/<name>/exemplars.jsonl`: one row per published piece with `medium / genre / grade (engagement×substance) / substance.level / split (train|dev|final) / skeleton / topic_keys`.
- **Noise filtered at ingest** (`build`): crawler boilerplate, near-dup recaptures, reply-chain flattening, AI summaries. `substance: low` rows (reaction-only, no transferable structure) are excluded from anchors by default (`pull` defaults).
- **Seed pieces** from the interview get grade priority — they anchor outlines first.
- **Split discipline** (`resplit`, clustered): generation and coaching touch `train` only; `dev` is for diagnostics; `final` is sealed for claims (unseal requires an explicit flag and a reason). Corpus representation is ground truth — generated bodies must match it (e.g. single-`\n` paragraphing for Threads; a blank-line mismatch alone can out a fake).

## Writing pipeline (v2)

1. **Load persona**: `author-interview.json` + packs (`personas/<name>/packs/`).
2. **Working brief** — keep a 9-field brief alive through the session (kind / purpose / reader / medium / length / materials / style basis / current stage / open gaps); refresh it on scope changes. It prevents context drift on long sessions and cuts repeated questions (ask few, decisive ones; when the author is stuck, offer 2–4 directions with one recommendation instead of more questions).
3. **Message first** — one sentence: what should remain with the reader (most authors think message-first; confirm via interview).
4. **Genre typing** — classify against the persona's measured genre set.
5. **[G1] Skeleton-anchored outline** — pull 1–2 *real* same-genre pieces (`registry.py pull`, grade-first; `skeleton_extract.py` for the slot map) and map the message onto their skeleton slots (opening subtype / development moves / transition / closing subtype). The outline names its anchor (`skeleton_anchor: <ref> — <slot mapping>`). Generic genre templates (`outline-playbooks.md`) are fallback only, and say so.
   - **Diversity guard**: across a batch, rotate anchors and subtypes — one anchor repeated mechanically is itself an AI tell.
6. **[G2] Outline approval (hard)** — no prose before approval (author, or explicit self-approval for autonomous runs).
7. **Draft by borrowing** — quote-level borrowing from published `train` pieces; frontmatter records `차용:` provenance.
8. **[G3] 4-lens review** — structural → reader → skeptic/fact → voice (voice last).
9. **Two non-compensatory diagnostic axes**:
   - style axis: `check_endings.py` (deterministic ending gate) + `band_scorer.py` (percentile-calibrated style bands; flags `over_typical` — *more author-like than the author* is an AI signal, and `insufficient_sample` on short pieces);
   - structure axis: `structure_scorer.py` (persona×medium L2 bands: paragraph/line rhythm, sentence-length spread, device placement; optional skeleton adherence via `--skeleton`).
   High style cannot compensate a structure miss, and vice versa. Output is diagnostic with 대역+왜+코칭, never a bare score.
10. **[Gate] `gate.py`** — deterministic: ending distribution, borrow-quote presence, base provenance, AI-cliché two-tier (`--mode copy` for persona fidelity, `--mode universal` for stricter general polish).

## Verification — blind A/B harness (the real test)

Self-scores are diagnostics. The acceptance test is a **blind panel**: mix ≥20 generated pieces with real controls (train split only — never spend sealed `final` pieces on rounds), unlabeled, in the *corpus representation*; ≥10 independent judges, each holding a different reference set of real pieces (controls excluded), vote authentic/fake + author attribution; a blind coordinator (not the generator) assembles packets and holds the answer key (hash-committed before verdicts). Calibration gate: judges must catch controls (<70% control accuracy voids the round). Loop generation→panel→coaching until the target pass rate; claims about the persona only from the sealed `final` split with a CI.

## Host contract (Claude Code + ChatGPT Work)

Four layers keep the skill dual-host:
1. **code** — stdlib-only Python, no network, no host discovery (`--data-root` is always explicit): runs in a Code Interpreter sandbox as-is.
2. **data** — everything persona-specific in `personas/<name>/` files; nothing hardcoded in code or prompts.
3. **host adapter** — thin per-host entry: Claude Code invokes via this SKILL.md; ChatGPT Work via the bundle manifest (`agents/openai.yaml`). Only this layer may differ.
4. **approval** — G2 and publish gates route to whatever approval surface the host has (terminal ask / chat confirm).

## Calibration checklist (per persona)

- [ ] Step 0 interview → `personas/<name>/author-interview.{md,json}`.
- [ ] `registry.py build` from published sources (never AI drafts) → spot-check noise filters on a sample.
- [ ] Induce skeleton/subtype dictionaries per medium×genre (opening/closing/transition subtypes with real refs).
- [ ] `structure_profiler.py` → measure style AND structure bands; record *why* each band is that genre's fingerprint.
- [ ] `registry.py resplit` → seal `final` before any optimization loop.
- [ ] Run one blind panel round as baseline before trusting any change.

## Design rules

- **Structure is first-class**: an outline without a real-piece anchor is a bug, not a draft.
- **Purpose over style** (the author's own craft hierarchy): style joins from the outline stage, but purpose / reader / genre rules always outrank it. When a fidelity device hurts delivery, drop the device — blind panels punish mechanically repeated devices as AI tells, so this hierarchy *raises* pass rates rather than trading against them. Revise order is fixed: purpose → structure → logic/evidence → reader → sentences → style (polish last; never start with automatic sentence polish).
- **Style intensity is declared**: cloning defaults to *strong* (structural habits, rhythm, narrative distance). Offer weak (feel only) / medium (word choice, breath, transitions) when the goal is "my message, lightly in their tone"; record the chosen intensity in the outline frontmatter and step down one level when strong-mode devices start violating the purpose hierarchy.
- **Rework path = reverse outline first**: for existing drafts, summarize each paragraph's role (same `skeleton_extract.py` slot map), mark duplicates / weak links / reorder wins, then repair only the named scope — never rewrite from scratch by default (`outline-playbooks.md` §6).
- **Flexible by constitution**: bands are ranges; out-of-band triggers diagnosis, not auto-reject. Hard gates only for identity (provenance) and readers (cliché flooding).
- **Own-corpus ground truth**: never import folklore bans or another author's bands; match the corpus text representation exactly.
- **Typos/looseness are not style to copy mechanically** — spontaneity can't be faked by insertion; treat as report-only signals.
