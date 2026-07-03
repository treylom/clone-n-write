---
name: clone-n-write
description: Use when drafting or reworking posts in a specific person's voice. Genre-typed outline templates + borrow-from-published-work drafting + deterministic pre-publish gates (ending distribution, AI-cliché reverse detection, provenance).
version: 1.0.0
---

# clone-n-write (generalized template)

> **Mission**: ① flexibly imitate how a real person *thinks while writing* — direction → outline → draft → self-edit — not just their surface style; ② use the same machinery to coach the writer to write better. Every gate, template, and numeric target below is a means to those two goals, never a mechanical mandate.

> This is the **generalized public template** of a skill run daily for one real author. Replace every `<placeholder>` and calibrate every number against **your** author's corpus before trusting it.

## Writing pipeline (8 steps)

1. **Genre typing** — classify the piece (e.g. reflection / informational / promotional / review). Use `type_profiler.py` calibrated on your corpus.
2. **[G1] Outline** — fill the genre's outline template (`outline-playbooks.md`). For *new* pieces, build the outline interactively: present 2–3 direction candidates (one-line core message each, one recommended) → author picks → template-filled outline → author refines.
3. **[G1.5] Craft check** — the outline names which "good opening" move it uses and which "common failure" it avoids (from the genre playbook). Loading the playbook isn't applying it; say which rows you used.
4. **[G2] Outline approval (hard)** — no prose before the outline is approved (by the author, or explicitly self-approved for autonomous pieces).
5. **Draft by borrowing** — pull 2–3 of the author's *published* pieces of the same genre from the corpus and borrow their moves (openings, connectives, closings). Templates are for judging output, not for stamping prose — mechanical template-filling reads stiff.
6. **[G3] 4-lens review** — structural → reader → skeptic/fact → voice, in that order (voice last). Each lens names what to fix first, it doesn't rewrite everything.
7. **Quantitative pass** — `quant_scorer.py` + `check_endings.py` against the genre's measured bands. Output is diagnostic ("your CV is X, the genre band is Y–Z — because…"), not a bare score.
8. **[Gate] `gate.py`** — final deterministic gate: ending-distribution guard, borrow-quote presence, base-provenance (drafts must derive from the author's published base, not bot text), AI-cliché two-tier check (`--mode copy` for full-fidelity persona work, `--mode universal` for stricter general polish).

## Calibration checklist (do once per persona)

- [ ] Build the corpus: `build_corpus.py` pointed at your author's published sources (never AI drafts).
- [ ] Calibrate `type_profiler.PROFILES` ending distributions from the corpus.
- [ ] Build both AI-cliché tiers from corpus counts (zero-occurrence = hard tier; present-but-rare = capped tier).
- [ ] Set `BOT_AUTHOR_HINTS`, `PERSONA_VAULT_ROOT`, and the path placeholders.
- [ ] Measure genre bands (ending %, sentence-length CV, marker rates) and record *why* each band is that genre's fingerprint — a number without a why is not a target, it's noise.

## Design rules

- **Flexible by constitution**: bands are ranges; out-of-band output triggers a diagnosis, not an auto-reject. The only hard gates are the ones that protect identity (provenance) and readers (cliché flooding).
- **Coach output**: every automated verdict carries the *why* from the calibration notes, so the writer learns the principle, not just the pass/fail.
- **Own-corpus ground truth**: never import banned-phrase folklore or another author's bands — measure your author.
