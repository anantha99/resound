# Task ID: 18

**Title:** Polish README for Demo Reviewer Experience

**Status:** pending

**Dependencies:** None

**Priority:** high

**Description:** Update README.md to meet the repo acceptance criteria: quickstart works in <5 minutes on fresh clone, explicitly frames this as a hiring-pitch artifact, and provides clear architecture pointers.

**Details:**

Update README.md according to PRD §3.2 acceptance criteria:

1. **Add explicit framing at top:**
```markdown
> **What is this?** A hiring-pitch artifact demonstrating a productizable voice-of-customer intelligence layer for Fulfil's D2C customers. This is a working proof-of-concept, not a v1 release.
```

2. **Simplify quickstart to 2-minute path:**
```markdown
## Quick start (2 minutes)

1. Clone and install:
   ```bash
   git clone <repo-url> resound && cd resound
   python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   pip install -e .
   ```

2. Configure API keys:
   ```bash
   cp .env.example .env
   # Edit .env: add OPENROUTER_API_KEY and REDDIT_* credentials
   ```

3. Verify:
   ```bash
   resound healthcheck --brand liquiddeath
   ```
   Should show green checks for API key and config.
```

3. **Add pointer to architecture:**
```markdown
## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for Mermaid diagrams of:
- System flow (5 layers + LLM gateway)
- LLM Gateway internals
- Data model
```

4. **Add "Source coverage" section:**
```markdown
## Source coverage

- **Reddit**: Fully wired, tested, demo-ready.
- **G2**: Scaffolded but rate-limit-fragile (Cloudflare). Disabled in shipped brand bundles.
- **Twitter**: Scaffolded, requires paid API tier for useful volume. Disabled in shipped brand bundles.
```

5. **Reference PRDs:**
```markdown
## Product specs

- [`docs/PRD.md`](docs/PRD.md) — Original product spec
- [`docs/PRD-openrouter.md`](docs/PRD-openrouter.md) — OpenRouter refactor spec
- [`docs/PRD-demo.md`](docs/PRD-demo.md) — Demo execution spec
```

6. **Clean up any stale content** that contradicts the demo state.

**Test Strategy:**

Verification:
- Fresh clone test: follow README quickstart on new machine/venv, complete in <5 min
- All code snippets in README are copy-paste executable
- All file links resolve (docs/ARCHITECTURE.md, docs/PRD.md, etc.)
- No TODO/FIXME comments in README
- Reviewer can find architecture diagram within 30 seconds of opening README
