# Task ID: 25

**Title:** Create Video Beat 3 Script (The Money Shot)

**Status:** pending

**Dependencies:** 16, 17

**Priority:** high

**Description:** Write the script and prepare file-editing demo for Beat 3 (Extensibility move, 1:10-2:00) showing Ridge onboarding as config-only task.

**Details:**

Prepare Beat 3 per PRD §4.3 — this is the critical beat:

1. **Write script:**
```
"Now watch. Onboarding a second brand — Ridge — is a configuration task, 
not an engineering one."

[SHOW: File tree of brands/liquiddeath/]
"Here's Liquid Death's config. Six files."

[TERMINAL: cp -r brands/liquiddeath brands/ridge]
"Copy the bundle."

[EDITOR: Show pre-prepared diffs]
"Edit brand.yaml — name and description.
Edit sources.yaml — different subreddits.
Edit understanding.md — Ridge's product taxonomy."

[TERMINAL: resound healthcheck --brand ridge]
"Health check... green."

[TERMINAL: resound run --brand ridge]
"And now signals are streaming for Ridge."

[PAUSE]

"Three minutes of YAML. No Python. This is the productization story for Fulfil — 
every D2C brand on the platform is a config bundle away."
```

2. **Pre-prepare the diffs:**
- Ridge bundle already created (Task 16)
- For recording, pretend to copy and edit:
  - Actually show the file tree
  - Actually run cp command (already done, but show it)
  - Show pre-prepared diffs in editor, paste in (don't type live)

3. **Editor setup:**
- Use VS Code or similar with file tree visible
- Pre-open brand.yaml, sources.yaml, understanding.md
- Have diff snippets ready to paste

4. **Timing:**
- File tree intro: ~5 seconds
- cp command: ~5 seconds
- Editor diffs: ~25 seconds
- healthcheck: ~5 seconds
- run command: ~5 seconds
- Closing statement: ~5 seconds
- Total: ~50 seconds

5. **Save:**
- `docs/demo-assets/beat3-script.md`
- `docs/demo-assets/ridge-diffs.md` (pre-prepared snippets)

**Test Strategy:**

Verification:
- Script reads aloud in 45-50 seconds
- Ridge bundle exists and healthcheck passes
- `resound run --brand ridge` streams signals
- Editor shows clear visual diffs
- Key message lands: config task, not engineering task
