# Task ID: 14

**Title:** Update README with OpenRouter Documentation

**Status:** pending

**Dependencies:** 2 ✓, 11

**Priority:** low

**Description:** Update README.md with comprehensive setup instructions, OpenRouter configuration, and model selection guidance.

**Details:**

Update `README.md` with:

1. **Header/Badge section**
   - Project description emphasizing OpenRouter flexibility
   - Badges: Python version, license, etc.

2. **Features**
   - Multi-model support via OpenRouter (200+ models)
   - Provider-agnostic architecture
   - Two-stage filter→classify for cost optimization
   - Per-stage model configuration

3. **Quick Start**
   ```bash
   # Clone and install
   git clone ...
   cd resound
   pip install -e .
   
   # Configure
   cp .env.example .env
   # Edit .env with OPENROUTER_API_KEY
   
   # Run
   resound poll-once --brand liquiddeath
   resound dashboard --brand liquiddeath
   ```

4. **Model Configuration**
   - Explain models.yaml structure
   - Show how to switch models
   - Cost comparison table (Claude vs GPT vs Llama)

5. **Architecture Overview**
   - Diagram of 5 layers + gateway
   - Configuration file reference

6. **Brand Configuration**
   - 7 files required
   - Example snippets

7. **Docker Deployment**
   - `docker compose up` instructions

8. **API Reference**
   - CLI commands
   - Environment variables

**Test Strategy:**

Review testing:
- Verify all code snippets in README work
- Test quick start on fresh machine
- Check all links are valid
- Review for clarity and completeness
