# Task ID: 28

**Title:** Execute Pre-Recording Checklist

**Status:** pending

**Dependencies:** 16, 17, 19

**Priority:** high

**Description:** Run through the complete pre-recording checklist from PRD §6 immediately before recording to verify all systems are operational.

**Details:**

Execute PRD §6 checklist items sequentially:

```
PRE-RECORDING CHECKLIST
========================

[ ] data/ directory exists in repo root
    $ ls data/

[ ] .env has working OPENROUTER_API_KEY
    $ grep OPENROUTER_API_KEY .env | head -c 30

[ ] RESOUND_CLASSIFIER_MODEL is set to a verified slug
    $ echo $RESOUND_CLASSIFIER_MODEL
    Test: resound poll-once returned success within last hour

[ ] Reddit credentials valid
    $ resound healthcheck --brand liquiddeath
    Shows: "✓ REDDIT_CLIENT_ID set" (green)

[ ] Memory pre-seeded with 30+ signals
    $ sqlite3 data/resound.db "SELECT COUNT(*) FROM signals WHERE brand_slug='liquiddeath';"
    Should be >= 30

[ ] Interesting signals exist:
    $ sqlite3 data/resound.db "SELECT COUNT(*) FROM classifications WHERE severity IN ('high','critical');"
    Should be >= 1
    $ sqlite3 data/resound.db "SELECT COUNT(*) FROM classifications WHERE action_class='immediate';"
    Should be >= 1
    $ sqlite3 data/resound.db "SELECT COUNT(*) FROM classifications WHERE root_cause_hypothesis IS NOT NULL AND root_cause_hypothesis != '';"
    Should be >= 1

[ ] Ridge bundle complete, healthcheck green
    $ resound healthcheck --brand ridge

[ ] Streamlit dashboard renders
    $ resound dashboard --brand liquiddeath
    Navigate to all 3 tabs, confirm no errors

[ ] G2/Twitter disabled in sources.yaml
    $ grep -A1 "g2:" brands/liquiddeath/sources.yaml
    $ grep -A1 "twitter:" brands/liquiddeath/sources.yaml
    Both should show enabled: false

[ ] Terminal font >= 16pt
    Visually verify

[ ] Browser zoom adequate for dashboard
    Visually verify columns are legible

[ ] Notifications silenced
    macOS: Do Not Disturb on
    Windows: Focus Assist on

[ ] Microphone tested
    Record 10 seconds, play back, verify clarity
```

Run each item, document pass/fail.

**Test Strategy:**

All checklist items pass. If any fail:
- Fix the issue before proceeding
- Re-run failed item to confirm fix
- Do not proceed to recording until 100% pass
