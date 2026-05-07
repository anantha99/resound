# Task ID: 26

**Title:** Create Video Beat 4 Script (Architecture Credibility)

**Status:** pending

**Dependencies:** 21

**Priority:** medium

**Description:** Write the script and prepare model swap demonstration for Beat 4 (Architecture credibility, 2:00-2:30) showing LLM gateway flexibility.

**Details:**

Prepare Beat 4 per PRD §4.4:

1. **Write script:**
```
"Five layers. Each one is an interface; concrete implementations are pluggable. 
The LLM is a single gateway — switch from Claude to GPT to Gemini with one config edit."

[SHOW: ARCHITECTURE.md diagram in browser]
"Here's the system flow. Sources, understanding, routing, memory, feedback."

[ZOOM: LLM gateway box]
"All model calls go through this gateway."

[EDITOR: Show .env or models config]
"Change the model here..."

[EDIT: RESOUND_CLASSIFIER_MODEL from claude to gpt]

[TERMINAL: resound poll-once --brand liquiddeath]
"Next classification uses the new model."
```

2. **Browser preparation:**
- Open docs/ARCHITECTURE.md on GitHub (rendered Mermaid)
- Or use VS Code Markdown preview
- Pre-zoom to appropriate level

3. **Model swap demonstration:**
- From Task 21, know the exact edit to make
- Pre-stage .env file with cursor on the model line
- Make edit: `anthropic/claude-sonnet-4-5` → `openai/gpt-4.1`
- Show poll-once output (or cut to avoid wait time)

4. **Timing:**
- Architecture statement: ~8 seconds
- Diagram view: ~10 seconds
- Config edit: ~8 seconds
- Verification: ~4 seconds
- Total: ~30 seconds

5. **Save:**
- `docs/demo-assets/beat4-script.md`

**Test Strategy:**

Verification:
- Script reads aloud in 28-32 seconds
- Architecture diagram renders correctly in browser/preview
- Model swap edit is visible and clear
- Post-edit classification works (tested in Task 21)
