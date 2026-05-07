# Task ID: 21

**Title:** Verify and Document Model Swap Demo Flow

**Status:** pending

**Dependencies:** 17

**Priority:** medium

**Description:** Test and document the model swap demonstration (Beat 4) where the classifier model is changed via environment variable to prove architecture flexibility.

**Details:**

Prepare the model swap demonstration for Beat 4 (§4.4 Architecture credibility):

1. **Test model swap flow:**
```bash
# Start with Claude (current default)
echo $RESOUND_CLASSIFIER_MODEL
# Should show: anthropic/claude-sonnet-4-5

# Run a classification and note model_used
resound poll-once --brand liquiddeath
# Check last classification model in DB

# Change to GPT
export RESOUND_CLASSIFIER_MODEL=openai/gpt-4.1
# Or edit .env file

# Run again
resound poll-once --brand liquiddeath
# Verify new model appears in classification
```

2. **Verify model_used is visible in dashboard:**
- Check if Classification model info surfaces in dashboard views
- If not currently visible, note for potential enhancement (NOT blocking for demo)

3. **Document tested model slugs that work:**
- `anthropic/claude-sonnet-4-5` ✓
- `openai/gpt-4.1` ✓ (or current equivalent)
- `google/gemini-2.5-pro` (optional test)

4. **Prepare .env.demo file:**
```bash
# Copy .env to .env.demo-claude and .env.demo-gpt
# Pre-configure both for quick swap during recording
```

5. **Write recording script notes:**
- Exact file to show (.env or which config)
- Exact edit to make on camera
- Expected output to verify model changed

**Test Strategy:**

Verification:
- Model swap from Claude to GPT works without code changes
- Classification still succeeds with alternate model
- Process restart picks up new model (no caching issues)
- Recording script notes are clear enough to execute on camera in <30 seconds
