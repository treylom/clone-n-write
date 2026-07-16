---
name: clone-n-write
description: Use when drafting or reworking posts in a specific person's voice AND structure. Onboarding interview + graded exemplar registry + skeleton-anchored outlines + non-compensatory style/structure diagnostics + blind A/B harness.
version: 2.2.0
---

# clone-n-write v2 (generalized template)

> **Mission**: reproduce how a real person *thinks while writing* — message → outline → draft → self-edit — including the **structure** of their pieces (openings, paragraph rhythm, transitions, closings), not just surface style. Every gate and number is a means, never a mechanical mandate.

> Generalized public template. All persona data lives under `personas/<name>/` (never ship a real person's data in public forks). Calibrate every number against **your** author's corpus.

## Session start — persona resolution (run this before anything else)

1. **Resolve the data root**, in this order: an explicit `--personas-dir` argument → a `personas/` directory in the current working directory → the skill's bundled `personas/` as last resort. **Never store author data inside a plugin cache** — caches are wiped on update; if the skill is running from one, create and use `./personas/` in the user's workspace instead. Hosts without a persistent filesystem (chat sandboxes): treat persona data as session-scoped — ask the author to paste/attach their profile at start, and hand every artifact back at the end for them to keep. Committing or pushing results anywhere is always the author's own workflow, never automated here.
2. **Pick the persona**: list `personas/*/`. Exactly one → auto-select and say which. Several → ask the author. None → this is a new persona; go to Step 0.
3. **Load-or-interview branch**: if `personas/<name>/author-interview.json` exists, load it (plus `packs/`) and **skip Step 0**; run the interview only when the file is missing, and re-run it only on the author's explicit request.
4. **Self-contained by design**: building a corpus needs nothing beyond the author's published texts as plain files — `registry.py build` ingests them directly. No knowledge-management stack or external service is assumed.

## Step 0 — Onboarding interview (once per persona)

Ask the author ~8 questions and persist to `personas/<name>/author-interview.md` (+ `.json` mirror for tools):
thinking origin (message-first? scene-first?) / "what feels off" signals / seed pieces they consider their best (with why) / medium→structure mapping / appeal of the clone target in 3 axes / noise criteria / must-keep & never-use expressions / imagined reader.
**Delivery: one batched message.** Send all ~8 as a single numbered list the author answers in one reply (partial answers fine — follow up only on gaps). Do not drip them one per turn, and do not skip the interview just because the author already named a piece they want to write — capture the piece request, run the batch, then start the piece. Hosts without interactive question widgets (Codex CLI, plain chat): the numbered plain-text list *is* the widget.
Every writing session loads this file first; hosts that persist context re-inject it at session start. The interview is the author's *tacit knowledge* — treat it as spec, not decoration.

## Data layer — exemplar registry (not a flat corpus)

`registry.py {build,pull,add,resplit,stats}` maintains `personas/<name>/exemplars.jsonl`: one row per published piece with `medium / genre / grade (engagement×substance) / substance.level / split (train|dev|final) / skeleton / topic_keys`.
- **Noise filtered at ingest** (`build`): crawler boilerplate, near-dup recaptures, reply-chain flattening, AI summaries. `substance: low` rows (reaction-only, no transferable structure) are excluded from anchors by default (`pull` defaults).
- **Seed pieces** from the interview get grade priority — they anchor outlines first.
- **Split discipline** (`resplit`, clustered): generation and coaching touch `train` only; `dev` is for diagnostics; `final` is sealed for claims (unseal requires an explicit flag and a reason). Corpus representation is ground truth — generated bodies must match it (e.g. single-`\n` paragraphing for Threads; a blank-line mismatch alone can out a fake).

## Writing pipeline (v2)

1. **Load persona**: `author-interview.json` + packs (`personas/<name>/packs/`).
2. **Working brief** — keep a 9-field brief alive through the session (kind / purpose / reader / medium / length / materials / style basis / current stage / open gaps); refresh it on scope changes. **Piece kickoff = one batched brief.** When the author asks for a specific piece, collect every unknown brief field in a single numbered message (typically 3–6 questions at once, same batch style as Step 0) instead of one question per turn — one round trip, then write. Fields already known from the interview, the request itself, or earlier in the session are never re-asked. *After* kickoff, keep questions rare and decisive; when the author is stuck, offer 2–4 directions with one recommendation instead of more questions.
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

## Verification — pairwise blind A/B (the real test)

Self-scores are diagnostics. The acceptance test is a **reference-primed pairwise panel** (author-specified design):
1. **Prime the judges**: every judge first studies a reference set of the author's *real* pieces (length-stratified, ~15; train split only — never spend sealed `final` pieces on rounds), presented as verbatim files.
2. **A/B pairs**: for each generated piece, produce a *plain counterpart* — same topic, written with **no persona conditioning** (topic extracted as a neutral brief so no phrasing leaks). Judges see each pair blind (deterministic side-flips per judge) and answer: which one is the author's style — **A / B / neither**. Never force a pick; "neither" counts against the clone.
3. **Metric**: clone vote share and pair-majority wins, against the author's target (default ≥90%). Vote hygiene: drop degenerate votes (placeholder reasons, schema failures) and report the dropped count — a noisy panel is a finding, not a shrug.
4. Absolute real-vs-generated panels (with real controls + calibration gate) remain a *final-claim* instrument on the sealed `final` split with a CI — not the improvement loop's primary meter.

## Repair loop (panel → corpus-verified tells → data-layer fix)

Each round below target feeds the next repair — this loop is the product as much as the prose is:
1. **Collect every losing-vote reason** (and `style_cues`) from the panel — that is the diagnosis corpus.
2. **Verify each candidate tell against the author's own corpus** before acting: measure its frequency in real pieces vs generated ones (e.g. a punctuation mark at 0/350 real vs 4/20 generated = hard ban; a device the author does use, just less, = genre-conditioned or soft). Judge claims are hypotheses, not rules — own-corpus ground truth decides.
3. **Persist verified tells to the persona data layer** — the interview's taboo slot (`Q7`) with provenance (which round, which evidence, real-vs-generated counts) and an `enforcement` grade (hard / soft / report-only). **Never patch skill code with persona-specific bans.**
4. **Repair pass**: rewrite generated pieces surface-only (content, borrowing, facts, length invariant) applying the persisted rules — or regenerate if the miss is structural. Then next round with fresh judges.
5. Stop at target; keep the skill light — prefer *replacing* a wrong rule over adding a new one, and re-check skill size each cycle.

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
