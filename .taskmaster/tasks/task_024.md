# Task ID: 24

**Title:** Create Video Beat 2 Script and Terminal Setup

**Status:** pending

**Dependencies:** 17

**Priority:** high

**Description:** Write the script and prepare terminal/dashboard setup for Beat 2 (Liquid Death running live, 0:20-1:10) with curated signal walkthrough.

**Details:**

Prepare Beat 2 per PRD §4.2:

1. **Write script:**
```
"Here's Resound configured for Liquid Death. Real public Reddit data, 
classified by an LLM, routed to a plausible internal owner."

[TERMINAL: resound run --brand liquiddeath]
"We're polling Reddit for mentions. Each signal gets classified and routed."

[CUT TO: Dashboard]
"Here's the dashboard. Let me walk through one specific signal."

[CLICK: Select the pre-curated signal]
"This customer complaint came from Reddit. The classifier identified it as 
a [area] issue, severity [severity], action class [action_class].

It was routed to [owner] because [rule that matched].

And here in the memory browser — every signal accumulates. This is the asset 
that compounds."
```

2. **Terminal preparation:**
- Set terminal font to 16pt+ minimum
- Use dark theme for contrast
- Pre-position terminal window for screen capture
- Test `resound run --brand liquiddeath` streams signals visibly

3. **Dashboard preparation:**
- Pre-launch: `resound dashboard --brand liquiddeath`
- Set browser zoom for readability
- Pre-navigate to Live feed tab
- Identify the curated signal row (from Task 17)

4. **Curated signal selection:**
- Must have: interesting content, clear classification, specific routing
- Document: signal_id, expected area, severity, action_class, owner
- Prepare what to say about each field

5. **Timing notes:**
- Terminal run: ~10 seconds
- Dashboard overview: ~15 seconds
- Signal walkthrough: ~20 seconds
- Memory browser note: ~5 seconds
- Total: ~50 seconds

6. **Save:**
- `docs/demo-assets/beat2-script.md`
- `docs/demo-assets/curated-signal.md` (signal details)

**Test Strategy:**

Verification:
- Script reads aloud in 45-50 seconds
- Terminal font is readable at 1080p
- Dashboard columns are legible at recorded zoom
- Curated signal exists in memory with expected classification
- Can smoothly navigate to signal in dashboard
