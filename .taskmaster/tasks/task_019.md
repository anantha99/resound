# Task ID: 19

**Title:** Remove TODO/FIXME/Placeholder Comments from Customer-Visible Files

**Status:** pending

**Dependencies:** 16

**Priority:** high

**Description:** Audit and clean all brand config files and customer-visible code to remove any TODO, FIXME, or placeholder comments that would undermine credibility during repo review.

**Details:**

Per PRD §8 definition of demo-ready: "No `# TODO`, `# FIXME`, or commented-out experimental code in customer-visible files."

1. **Search for issues:**
```bash
grep -rn "TODO\|FIXME\|XXX\|HACK" brands/ src/resound/
grep -rn "# placeholder\|# stub\|# temp" brands/ src/resound/
```

2. **Customer-visible files to audit:**
- `brands/liquiddeath/*.yaml`
- `brands/liquiddeath/*.md`
- `brands/ridge/*.yaml`
- `brands/ridge/*.md`
- `brands/fulfil/*.yaml` (stays in repo per PRD, just not on camera)
- `brands/fulfil/*.md`
- `src/resound/dashboard/app.py`
- `README.md`
- `docs/ARCHITECTURE.md`

3. **For each TODO found:**
- Either implement the feature (if trivial)
- Or delete the comment entirely (if out of scope for demo)
- Do NOT leave as-is

4. **Check for commented-out code blocks:**
- Remove any `# import foo` or `# def unused_function()` blocks
- If code is not active, it should not be in the file

5. **Verify G2/Twitter sources are cleanly disabled:**
- In `brands/liquiddeath/sources.yaml` and `brands/ridge/sources.yaml`:
  - `g2.enabled: false` with no explanation comment needed
  - `twitter.enabled: false` same

**Test Strategy:**

Verification:
- `grep -rn "TODO\|FIXME" brands/ src/resound/` returns no matches
- `grep -rn "# placeholder" brands/` returns no matches
- Visual review of all brand config files shows professional, complete content
- No commented-out import statements in src/resound/*.py
