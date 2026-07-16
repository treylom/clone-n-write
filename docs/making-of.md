# Making of clone-n-write — how we repaired a style clone to 90%

> The process record behind this repo: two days of blind A/B panels, corpus-verified repairs, and one design correction from the author that changed everything. Numbers below are from the actual runs (July 2026, persona: a Korean Threads/longform author with a 1,127-piece corpus). No persona data ships in this repo — see `personas/README.md`.

## The goal

Reproduce how a real person *thinks while writing* — message → outline → draft → self-edit — including the **structure** of their pieces, not just surface style. The acceptance bar, set by the author: a blind panel should pick the clone as "the author's style" **90%+ of the time** against a plain (non-conditioned) counterpart.

## The verification design that failed first

Our first instinct was an absolute panel: mix real and generated pieces, ask judges "real or fake?", seal everything with a hash-chain ledger. It was rigorous — and it collapsed. The pre-registered control gate (a floor on judges' accuracy over *real* pieces) fired at unblind time and invalidated the round: the panel itself had drifted, so its verdicts proved nothing.

The author then corrected the design itself:

1. Prime every judge on ~15 of the author's real pieces first (length-stratified, train split only).
2. Then run **pairwise A/B**: for each generated piece, produce a *plain counterpart* — same topic (extracted as a neutral brief so no phrasing leaks), no persona conditioning. Judges see each pair blind and answer: which is the author — **A / B / neither**. Never force a pick.
3. Repair the skill until the clone wins 90%+, and report *why* each losing vote happened.
4. Keep the skill light while doing it.

Deterministic side-flips per judge, answer key stored separately from the blinded files. This relative design is what the "Verification" section of `skills/clone-n-write/SKILL.md` now specifies.

## The repair loop — judge claims are hypotheses, the corpus decides

Every round below target, we collected **every losing-vote reason**, then verified each claimed "tell" against the author's own corpus (350 real pieces) before acting:

- em-dash: 0/350 real vs 4/20 generated → **hard ban** (confirmed)
- hook-question openers: 1.7% of real pieces → genre-restricted, not banned (conditional)
- "the author always numbers lists `1)`": measured `1.` 34 vs `1)` 34 — a tie → **rejected** (folklore)
- paragraph rhythm: real pieces run a *median of 1 sentence per paragraph block* (3+ sentence blocks: only 5%); our two worst losers were single 9-sentence slabs → new rule (confirmed)
- promo-genre endings: real promo posts run formal:casual endings ≈ 1.8:1; the losing clone ran 2:7 inverted → quantified band (confirmed)

Verified tells go into the **persona data layer** (the interview's taboo slot, with provenance and an enforcement grade) — never hardcoded into skill code. We also over-corrected once (forcing plain-register rules onto promo posts, prose-ifying lists the author actually writes) and lost a round to it. The fix was **replacing** the wrong rule with a genre-conditional one, not stacking a new rule on top.

## The trajectory

| round | set | clone vote share | pair majorities | note |
|---|---|---|---|---|
| 1 | 20 pairs | 72.3% | 15/20 | tells: em-dash, hook openers, staccato |
| 2 | 20 (repaired) | 77.7% | 16/20 | over-correction found → rules replaced |
| 5 | 20 (final repairs) | 85.7% | 19/20 | the ceiling of post-hoc repair |
| 6 | **30 new (rules baked into generation)** | **91.8%** | 29/30 | **crossed 90%** |
| 6 | 50 combined | 87.6% | 47/50 | sample doubled at author's request |
| 7 | 20 regenerated from scratch | 85.2% | 18/20 | regeneration beats patching (+3.4pp) |
| 8 | mini-cycle on the 2 worst losers | — | +1 pair | paragraph-rhythm rule: 5/5 win |
| final | regenerated-20 standing | **89.9%** [81.9, 94.6] | **19/20 (95%)** | new-30 set holds 91.8% |

**The headline finding: post-hoc repair plateaus (~85%), baking the learned rules into generation crosses 90% (91.8%).** The repair loop's real product is the rule set it verifies — spend it on the *next* generation, not on patching the last one.

## Panel hygiene (it will try to cheat you)

- Placeholder votes ("test reason") appeared in round 1. A schema `minLength` stopped those — and by round 5 degenerate votes *evolved* into English padding that satisfied the length check. Final defense is a post-hoc scorer filter, plus a rule: **always report the dropped-vote count**. A noisy panel is a finding, not a shrug.
- When the metric's real judge is a human (taste), don't let bots re-measure their way to convergence. At 89.9% with 90% inside the CI, the call went to the author — who closed the loop.
- Genre stability differs: our promo genre failed on a *different axis every round* (register → paragraphing → ending ratio). That instability is itself an output; carry it as a caveat.

## What generalizes

Everything above is persona-independent process: interview → registry with split discipline → skeleton-anchored generation → reference-primed pairwise blind panels → corpus-verified repair into the data layer → bake rules into generation → author-set stopping rule. The persona-specific part (the actual tells, the bands, the corpus) lives entirely under `personas/<name>/`, which never ships. Calibrate every number against **your** author's corpus — importing another author's bans is exactly the folklore this loop exists to reject.
