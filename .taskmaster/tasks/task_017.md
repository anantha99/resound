# Task ID: 17

**Title:** Pre-seed Liquid Death Memory with 30+ Classified Signals

**Status:** pending

**Dependencies:** 16

**Priority:** high

**Description:** Run the pipeline multiple times to accumulate at least 30 classified signals for Liquid Death, ensuring diversity in severity, action_class, and areas for a compelling demo walkthrough.

**Details:**

Execute the pre-recording checklist item §6 to build a rich memory state:

1. **Initial seeding:**
```bash
resound poll-once --brand liquiddeath
# Wait 2-3 minutes for rate limits
resound poll-once --brand liquiddeath
resound poll-once --brand liquiddeath
```

2. **Verify signal diversity in memory:**
- Check SQLite database: `sqlite3 data/resound.db "SELECT severity, COUNT(*) FROM classifications GROUP BY severity;"`
- Must have at least 1 signal with `severity=high` or `severity=critical`
- Must have at least 1 signal with `action_class=immediate` or `action_class=sprint`
- Must have at least 1 signal with `root_cause_hypothesis` filled in

3. **Curate walk-through signal:**
- Query database for a signal that has:
  - Non-trivial content (actual complaint, not just fandom)
  - Clear routing decision (matched a specific rule)
  - Interesting root_cause_hypothesis
- Document the `signal_id` to use in the video walkthrough (Beat 2)

4. **Verify dashboard renders:**
```bash
resound dashboard --brand liquiddeath
# Navigate to each tab, confirm data displays
```

5. **Export backup:**
- Copy `data/resound.db` to `data/resound-demo-backup.db` for recovery if needed

**Test Strategy:**

Verification checklist:
- [ ] `SELECT COUNT(*) FROM signals WHERE brand_slug='liquiddeath'` >= 30
- [ ] At least one signal has severity=high or severity=critical
- [ ] At least one signal has action_class=immediate
- [ ] At least one signal has non-empty root_cause_hypothesis
- [ ] Dashboard Live feed tab shows data
- [ ] Dashboard Memory browser tab shows data
- [ ] Dashboard Routing audit tab shows routed signals with owners
- [ ] Backup database exists at data/resound-demo-backup.db
