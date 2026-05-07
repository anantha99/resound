# Resound — Demo PRD

**Version:** 1.0
**Status:** Draft
**Last updated:** April 2026
**Format:** Taskmaster-AI compatible (each section has acceptance criteria; Appendix B maps to tasks)

---

## 1. Summary

This is the demo PRD — the execution spec for the artifact we ship to Fulfil. It is **not** a product PRD. The product PRD is [PRD-openrouter.md](PRD-openrouter.md). This document answers a different question: "what proves, in three minutes and one private repo link, that we can build a deployable Resound that Fulfil could productize for their D2C customers?"

The demo's job is to make a Fulfil engineering or founding team member think two things:

1. **"This works."** Real ingestion, real classification, real routing, real persistence. Not vapor.
2. **"This person thinks about our customers, not just our company."** The pitch is positioned around D2C brands on Fulfil's platform — Liquid Death, Ridge, HexClad — not around Fulfil itself. The candidate's value-add is commercial empathy, not just code.

If those two beliefs land, the demo succeeds. Everything else is decoration.

## 2. Audience and intent

**Audience:** Fulfil engineering / founding / product leadership. Reviewers who will (a) watch a 3-minute video and (b) clone a private repo to verify the architecture is real.

**Intent:** Hiring conversation. The candidate is making the case that they should be on the team and that this product concept is something Fulfil could extend, productize, or sell to their D2C customer base.

**Beliefs to install (in order):**

1. The candidate ships clean, modular, deployable systems — not prototypes.
2. The candidate thinks in terms of *Fulfil's customers*, not Fulfil itself.
3. Onboarding a new D2C brand to this product is a configuration task, not an engineering task — which means Fulfil could productize it across their book.
4. The architecture is honest — five pluggable layers, single LLM gateway, append-only memory — and would survive an internal code review.

**Beliefs to NOT install (avoid):**

- "This is a finished product." It isn't, and pretending otherwise gets caught at repo review.
- "This is for Fulfil's internal use." Strategically wrong framing; the product is for Fulfil's customers.
- "Look how clever the LLM is." The classifier is a means, not the message.

## 3. Deliverables

Two artifacts, mutually reinforcing.

### 3.1 The video (~3 minutes, recorded)

A tight elevator pitch. Recorded screencast (Loom or equivalent), narrated. No live audience, no Q&A. Re-recordable until clean.

**Acceptance criteria:**
- Total runtime between 2:45 and 3:15.
- Voiceover is clear, scripted, and rehearsed (not extemporaneous).
- Every on-screen click has a narration beat — no silent screen movement.
- Cuts are clean; no waiting for slow operations on camera (pre-cache, pre-seed, edit out).
- One re-take maximum on any beat — if a beat takes more, the script is wrong, not the take.

### 3.2 The repo (private GitHub, link in video description)

The credibility check. A Fulfil engineer clones it, reads the README, and forms an opinion in under five minutes.

**Acceptance criteria:**
- Repo is private; access shared with named Fulfil reviewers only.
- README's "quickstart" works on a fresh clone with no prior context. Reviewer can `pip install -e .` and `resound healthcheck --brand liquiddeath` in under two minutes.
- Architecture diagram ([ARCHITECTURE.md](ARCHITECTURE.md)) renders in GitHub.
- At least two brand bundles ship: `liquiddeath` (the on-camera primary) and `ridge` (the extensibility beat). Both have all six config files filled in honestly — no `# TODO` placeholders in customer-visible config.
- Commit history is presentable. Squash any "wip", "fix", "ugh" commits before sharing.
- README explicitly names this is a hiring-pitch artifact, not a v1 product release. Honesty signals confidence.

## 4. The 3-minute beat sheet

The video is six beats. Each beat has a target duration, a script-style cue, and an on-screen criterion.

### 4.1 Beat 1 — The hook (0:00–0:20, 20s)

**Cue:** "Every D2C brand on Fulfil's platform — Liquid Death, Ridge, HexClad — has the same blind spot. Customer voice is scattered across Reddit, G2, Twitter. No shared memory, no closed loop. They lose deals over objections that product would have heard six months ago."

**On-screen:** Title card (Resound logo), then a visual of fragmented signals — a static collage of a Reddit thread, a G2 review, a Twitter mention.

**Acceptance:** Audience knows by 0:20 (a) what the problem is and (b) that this is positioned for *Fulfil's customers*, not Fulfil itself.

### 4.2 Beat 2 — Liquid Death running live (0:20–1:10, 50s)

**Cue:** "Here's Resound configured for Liquid Death. Real public Reddit data, classified by an LLM, routed to a plausible internal owner."

**On-screen:**
- Terminal: `resound run --brand liquiddeath` — show 5–10 signals stream in.
- Cut to dashboard (`resound dashboard --brand liquiddeath`).
- Walk through one specific routed signal: complaint → classification (area, severity, action class, root cause) → which owner it routed to and why.
- Show the memory browser tab — "every signal accumulates here, append-only."

**Acceptance:** The reviewer sees an actual classified signal with an actual routing decision and an actual rule trace. Not a slide.

### 4.3 Beat 3 — The extensibility move (1:10–2:00, 50s) — *the money shot*

**Cue:** "Now watch. Onboarding a second brand — Ridge — is a configuration task, not an engineering one."

**On-screen:**
- File tree: `brands/liquiddeath/`. Six YAML/markdown files visible.
- `cp -r brands/liquiddeath brands/ridge`.
- Edit `brand.yaml`, `sources.yaml`, `understanding.md` — show the diffs in an editor (not type live; pre-prepared, paste in for the recording).
- `resound healthcheck --brand ridge` → green.
- `resound run --brand ridge` → signals stream for Ridge.

**Cue close:** "Three minutes of YAML. No Python. This is the productization story for Fulfil — every D2C brand on the platform is a config bundle away."

**Acceptance:** The reviewer believes adding a third brand (theirs, or any of Fulfil's customers) is genuinely a config-file task. This is the beat the whole video is built around.

### 4.4 Beat 4 — Architecture credibility (2:00–2:30, 30s)

**Cue:** "Five layers. Each one is an interface; concrete implementations are pluggable. The LLM is a single gateway — switch from Claude to GPT to Gemini with one config edit."

**On-screen:**
- The architecture diagram from [ARCHITECTURE.md](ARCHITECTURE.md) — full system flow.
- Quick zoom on the LLM gateway box.
- Show `.env` or `models.yaml` — change `RESOUND_CLASSIFIER_MODEL` from `anthropic/claude-sonnet-4-5` to `openai/gpt-4.1`. Restart. Next signal classified shows new `model_used`.

**Acceptance:** The reviewer sees that model choice is not hardcoded, that the architecture is intentional, and that this would survive a code review.

### 4.5 Beat 5 — The strategic close (2:30–3:00, 30s)

**Cue:** "I built this because Fulfil's customer base is the most interesting D2C portfolio in the market, and they all have this problem. This is a product line for Fulfil — a Fulfil-platform extension your customers can opt into. New brand onboarded in an afternoon. Append-only memory layer they own forever. Repo's linked below — happy to walk through the architecture."

**On-screen:** Final dashboard view, both brands in the brand picker. Title card with name + email + repo URL.

**Acceptance:** The reviewer ends knowing (a) what the product is for, (b) what the candidate is asking for, and (c) where to look next.

### 4.6 Hidden beat 0 — What you're NOT showing

Things that exist in the codebase but **stay off camera** because they're either flaky or off-message:

- G2 source (Cloudflare-blocks unpredictably).
- Twitter source (free tier returns nothing useful).
- Empty/error fallback classifications.
- The Fulfil brand bundle (would muddy the "for your customers" framing).
- Incomplete features from the OpenRouter PRD (no `models.yaml`, no `llm_calls` table, no telemetry tab).

**Acceptance:** None of these surfaces appear on screen. None are referenced in the narration.

## 5. Demo scope

### 5.1 In scope (must work flawlessly on camera)

- Reddit ingestion against Liquid Death + Ridge subreddits and search terms.
- OpenRouter classification using a verified-current model slug.
- Rules-based routing with `liquiddeath/routing.yaml` and `ridge/routing.yaml` producing visibly correct decisions.
- SQLite memory persisting across runs.
- Streamlit dashboard rendering: live feed, memory browser, routing audit.
- Healthcheck command returning green for both brands.
- One model swap (Claude → GPT or Gemini) demonstrated by editing one config and restarting.

### 5.2 Out of scope (deliberately deferred)

- G2 scraper (Cloudflare unreliable). Source is in the repo; not on camera.
- Twitter source (paid tier required for useful volume). In the repo with a graceful no-op.
- Two-stage filter→classify (single classify is fine for the demo).
- LLM telemetry / cost dashboard tab.
- `models.yaml` per-stage model selection (env var swap suffices for the demo).
- `llm_calls` audit table.
- Docker / docker-compose (mentioned in repo README as next step; not required for the demo).
- Live Slack/email feedback (file-based feedback is what's shown).
- The Fulfil brand bundle stays in the repo as an "and you could even point this at yourselves" footnote in the README. Not on camera.

## 6. Pre-recording checklist

Run this in order, immediately before the first take. Every box must be checked or the take aborts.

- [ ] `data/` directory exists in the repo root.
- [ ] `.env` has a working `OPENROUTER_API_KEY`.
- [ ] `RESOUND_CLASSIFIER_MODEL` is set to a slug that returned a successful classification within the last hour.
- [ ] Reddit credentials in `.env` are valid (verified by `resound healthcheck --brand liquiddeath` returning green).
- [ ] Memory has been pre-seeded with at least 30 classified signals for Liquid Death (run `resound poll-once --brand liquiddeath` 2–3 times).
- [ ] At least one signal in memory has each of: `severity=high`, `severity=critical`, `action_class=immediate`, a non-trivial `root_cause_hypothesis`. Curate by running poll-once until interesting signals show up.
- [ ] `brands/ridge/` exists with all six config files. `resound healthcheck --brand ridge` returns green.
- [ ] Streamlit dashboard renders without errors at `localhost:8501` for both brands.
- [ ] G2 and Twitter sources are commented out or absent from `brands/liquiddeath/sources.yaml` and `brands/ridge/sources.yaml` to prevent on-camera failure.
- [ ] Terminal font is large enough to read in 1080p (≥16pt).
- [ ] Browser zoom on the dashboard is set high enough that columns are legible.
- [ ] Notifications are silenced. macOS Do Not Disturb / Windows Focus Assist on.
- [ ] Microphone level tested.

## 7. Failure modes and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| OpenRouter model returns a fallback Classification on camera | Medium | Pre-verify the slug 1 hour before recording. If it fails mid-take, abort take, switch model in `.env`, restart from beat 2. |
| Reddit API rate-limit hits during recording | Low | Use pre-seeded memory rather than live polling for the dashboard beat. Live polling shown only briefly in beat 2. |
| Classifier produces an obviously wrong classification on a hand-walked signal | Medium | Pick the walk-through signal off-camera in advance. Don't pick on the fly. |
| Demo machine runs slow / lag visible | Low | Pre-warm the dashboard. Pre-cache. Edit out any pause longer than 1.5s. |
| Repo reviewer clones it and the README quickstart fails | High | Run the full README quickstart on a clean machine / fresh venv before sending the link. |
| Reviewer asks "why isn't G2 working" | Medium | README has a section: "Source coverage in v1 — Reddit is fully wired; G2 and Twitter are scaffolded but rate-limit-fragile and behind a flag." Honesty as defense. |

## 8. Definition of demo-ready

A single boolean: **would I send this to Fulfil tomorrow morning without further changes?**

The video is demo-ready when:
- Beats 1–5 all hit their acceptance criteria on a single recorded take with at most one cut per beat.
- A non-technical viewer can follow the narration without pausing.
- A technical viewer can identify the pipeline stages and architectural choices from the visual alone.
- Total runtime is between 2:45 and 3:15.

The repo is demo-ready when:
- A reviewer with no prior context can clone, install, and run `healthcheck` in under five minutes.
- README explicitly frames the artifact (hiring pitch, not v1 release) and points at the architecture diagram and PRDs.
- Both `liquiddeath` and `ridge` brand bundles are complete and the dashboard renders for both.
- No `# TODO`, `# FIXME`, or commented-out experimental code in customer-visible files.
- License file present (MIT or "all rights reserved" — pick one and own it).

When both are true, send. Don't keep polishing.

## 9. Open questions

- Do we want a written one-pager accompanying the video link in the cold email, or does the README cover that role? Default: README covers it; add a one-pager only if the cold-email recipient asks for "more."
- Should the video include the candidate's face (talking head intro/outro) or stay screencast-only? Default: screencast-only. Faster to record, less ego, more product-focused.
- Is the second brand really Ridge, or is there a Fulfil customer the candidate has stronger signal on? Default: Ridge — confirmed publicly as a Fulfil customer. If the candidate has a personal connection to a different one (HexClad, Hims & Hers, Wholly Veggie), swap in.

---

## Appendix A — Video production notes

**Tooling:** Loom or OBS for capture. Audacity / Loom built-in trimmer for cuts. iMovie or DaVinci Resolve only if a montage is needed (it shouldn't be).

**Format:** 1080p, 30fps, MP4. Stereo audio at -16 LUFS.

**Title card:** Resound logo (or wordmark), candidate name, role being applied for, contact email, repo URL. Held for 3 seconds at start, 5 seconds at end.

**Subtitles:** Auto-generated via Loom, manually corrected for product names (Resound, Fulfil, Liquid Death, Ridge).

**Distribution:** Single Loom share link. Private. Password-protect optional. Embed link in cold email + LinkedIn DM. Repo link in video description and pinned in chat.

## Appendix B — Mapping to Taskmaster tasks

This PRD is structured so `task-master parse-prd docs/PRD-demo.md` produces a tight, demo-prep punch list. Recommended decomposition:

- One task per **beat** (§4.1–§4.5) covering scripting, on-screen rehearsal, and recording.
- One task for **pre-recording checklist verification** (§6) — run end-to-end on the recording machine.
- One task per **repo polish item** (§3.2 acceptance criteria) — README quickstart verified, brand bundles complete, commit history squashed.
- One task for **second brand bundle creation** (`brands/ridge/`) — six config files, healthcheck green.
- One task for **failure-mode dry run** (§7) — run through each risk row, verify mitigation works.
- One task for **send-readiness gate** (§8) — final checkbox before the email goes out.

Total expected: ~12–15 tasks, all completable in a focused weekend.
