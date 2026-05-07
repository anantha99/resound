# Task ID: 5

**Title:** Implement LLM Routing Tiebreaker

**Status:** pending

**Dependencies:** 1 ✓, 2 ✓, 4

**Priority:** medium

**Description:** Add optional LLM-based routing fallback when no rule matches and classification confidence is low.

**Details:**

1. Create `src/resound/prompts/routing_tiebreaker.py`:
```python
TIEBREAKER_PROMPT_V1 = '''You are a routing assistant. Given a signal's classification and a list of potential owners, pick the single best owner.

Signal summary: {summary}
Area: {area}
Severity: {severity}
Action class: {action_class}

Candidate owners:
{candidates}

Return JSON: {"owner_id": "@handle or #channel", "reasoning": "brief explanation"}'''
```

2. Update `RulesRouter` to accept optional `gateway: LLMGateway`:
```python
def route(self, signal: RawSignal, classification: Classification, gateway: LLMGateway | None = None) -> Route:
    # ... existing rule matching ...
    
    # If no rule matched and confidence < 0.6 and gateway provided:
    if no_match and classification.confidence < 0.6 and gateway:
        return self._llm_tiebreak(classification, gateway)
    
    # Otherwise return default route
```

3. Add `_llm_tiebreak()` method that:
   - Builds candidate list from people.yaml entries
   - Calls gateway.complete() with 'routing_tiebreaker' stage
   - Parses response and returns Route with matched_rule='llm_tiebreaker'

4. Update Pipeline to pass gateway to router

5. Add config option in routing.yaml: `enable_llm_tiebreaker: true/false`

**Test Strategy:**

Unit tests:
- Test tiebreaker is NOT called when a rule matches
- Test tiebreaker is NOT called when confidence >= 0.6
- Test tiebreaker is called when no match and low confidence
- Test tiebreaker returns valid Route with correct owner
- Test tiebreaker failure falls back to default route
- Test llm_calls records tiebreaker invocations
