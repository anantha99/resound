# Task ID: 4

**Title:** Implement Two-Stage Filter→Classify Pipeline

**Status:** pending

**Dependencies:** 1 ✓, 2 ✓, 3 ✓

**Priority:** high

**Description:** Add a fast, cheap filter stage before full classification to reduce costs by filtering out ~70% of irrelevant signals.

**Details:**

1. Create `src/resound/prompts/filter.py` with filter prompt template:
```python
FILTER_PROMPT_V1 = '''You are a relevance filter. Given a signal and brand context, decide ONLY whether this signal is potentially about the specified brand.

Return a JSON object: {"is_about_brand": boolean, "confidence": float}

Be generous - when in doubt, say true. The full classifier will make the final call. Say false only for clear false positives (brand name mentioned but clearly about something else).'''
```

2. Create `src/resound/classifiers/two_stage.py` with `TwoStageClassifier`:
```python
class TwoStageClassifier(Classifier):
    def __init__(self, gateway: LLMGateway, brand_slug: str):
        self.gateway = gateway
        self.brand_slug = brand_slug
    
    def classify(self, raw: RawSignal, brand_context: str) -> Classification:
        # Stage 1: Filter with cheap model
        filter_result = self._filter(raw, brand_context)
        if not filter_result.is_about_brand:
            return Classification(
                is_about_brand=False,
                action_class=ActionClass.IGNORE,
                ...
            )
        
        # Stage 2: Full classification with quality model
        return self._classify(raw, brand_context)
```

3. Update `build_classifier()` in `src/resound/classifiers/__init__.py`:
   - Accept `gateway: LLMGateway` and `brand_slug: str` parameters
   - Return `TwoStageClassifier` by default
   - Support `RESOUND_CLASSIFIER_MODE=single` env var to skip filter stage

4. Update `Pipeline.__init__` to instantiate gateway and pass to classifier

5. Wire llm_calls recording: after each gateway.complete() call, call memory.record_llm_call()

**Test Strategy:**

Unit tests:
- Test filter stage rejects obviously off-topic signals (cost verification)
- Test filter stage passes potentially relevant signals to classify stage
- Test full classification runs only when filter passes
- Test fallback classification when filter model fails
- Test llm_calls table records both filter and classify stages
- Integration test: measure cost per 100 signals is within PRD target (<$0.50 filter + <$5 classify)
