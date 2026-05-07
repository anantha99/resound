# Task ID: 16

**Title:** Create Ridge Brand Configuration Bundle

**Status:** pending

**Dependencies:** None

**Priority:** high

**Description:** Create the complete Ridge brand bundle (6 YAML/markdown config files) as the second demo brand to prove the extensibility story that onboarding a new D2C brand is a configuration task, not an engineering task.

**Details:**

Create `brands/ridge/` directory with all 6 configuration files:

1. **brand.yaml**
```yaml
name: "Ridge"
description: "Minimalist wallets, rings, and everyday carry. DTC-first with retail expansion."
website: "https://ridge.com"
primary_contacts:
  - name: "Operator"
    role: "Resound admin"
    email: "ops@ridge.com"
```

2. **sources.yaml** - Enable Reddit only (G2/Twitter disabled per PRD §4.6):
```yaml
reddit:
  enabled: true
  subreddits:
    - ridge
    - EDC  # Everyday carry subreddit
    - wallets
  search_terms:
    - "ridge wallet"
    - "ridge ring"
  limit: 25

g2:
  enabled: false
twitter:
  enabled: false
```

3. **understanding.md** - Ridge-specific taxonomy:
- Product areas: wallets, rings, accessories, build quality, durability, RFID blocking
- Common complaints: card ejection issues, scratching, ring sizing
- Glossary: "The Ridge" (wallet), "Basecamp" (knife accessory)
- Include 4+ classification examples covering product complaint, shipping issue, positive review, false positive

4. **routing.yaml** - Rules matching Ridge's team structure:
- Critical → #exec
- Product quality → @product-lead
- Shipping/CS → #cs-team
- Default → #triage
- Low confidence → #review-queue

5. **people.yaml** - Placeholder owner mappings:
- @product-lead, @cs-lead, #exec, #cs-team, #triage, #review-queue

6. **views.yaml** - Saved dashboard views:
- "Critical this week"
- "Product defects"
- "Shipping issues"

**Test Strategy:**

Verification:
- `resound healthcheck --brand ridge` returns green with all config files loaded
- Source counts show reddit enabled, g2/twitter disabled
- Routing rules count matches routing.yaml
- People entries count matches people.yaml
- Understanding doc char count > 500 (substantive content)
- No `# TODO` or placeholder text in any config file
- Run `resound poll-once --brand ridge` and verify signals are ingested and classified
