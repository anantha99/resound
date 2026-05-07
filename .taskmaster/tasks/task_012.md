# Task ID: 12

**Title:** Create Operator Runbook Documentation

**Status:** pending

**Dependencies:** 11

**Priority:** low

**Description:** Write comprehensive operator documentation covering installation, brand onboarding, model configuration, and key rotation.

**Details:**

Create `docs/RUNBOOK.md` with sections:

1. **Quick Start**
   - Prerequisites (Python 3.12+, Docker)
   - Clone and install
   - Set up .env with API keys
   - Run first poll: `resound poll-once --brand liquiddeath`
   - View dashboard: `resound dashboard --brand liquiddeath`

2. **Brand Onboarding**
   - Create brand directory: `mkdir brands/newbrand`
   - Copy template files from existing brand
   - Edit brand.yaml (name, description, contacts)
   - Edit sources.yaml (enable/configure sources)
   - Edit understanding.md (taxonomy, glossary, examples)
   - Edit routing.yaml (rules, default route)
   - Edit people.yaml (owners, channels)
   - Optional: models.yaml for custom model selection
   - Test: `resound healthcheck --brand newbrand`

3. **Model Configuration**
   - Understanding models.yaml structure
   - Available models via OpenRouter
   - Cost vs quality tradeoffs per stage
   - Hot-swap procedure: edit models.yaml, restart
   - Testing: `resound models test --stage classify`

4. **API Key Rotation**
   - OpenRouter key rotation
   - Reddit/Twitter credential rotation
   - Zero-downtime rotation procedure

5. **Production Deployment**
   - Docker Compose deployment
   - Postgres setup and backups
   - Monitoring and alerting
   - Log aggregation

6. **Troubleshooting**
   - Common errors and solutions
   - Checking source health
   - LLM fallback debugging

**Test Strategy:**

Review testing:
- Follow runbook on fresh machine to verify accuracy
- Test all commands in runbook work as documented
- Have non-author follow runbook and note confusion points
- Verify brand onboarding takes <4 hours as per PRD target
