# Task ID: 15

**Title:** End-to-End Integration Testing

**Status:** pending

**Dependencies:** 4, 5, 9 ⧖

**Priority:** high

**Description:** Create comprehensive integration tests that verify the full pipeline from ingestion through classification and routing with the new gateway architecture.

**Details:**

1. Create `tests/integration/test_full_pipeline.py`:
```python
import pytest
from unittest.mock import Mock, patch
from resound.pipeline import Pipeline
from resound.gateway import OpenRouterGateway, LLMResponse
from resound.memory import SqlMemory

@pytest.fixture
def mock_gateway():
    gateway = Mock(spec=OpenRouterGateway)
    gateway.complete.return_value = LLMResponse(
        content='{"is_about_brand": true, ...}',
        model_used='anthropic/claude-sonnet-4-5',
        tokens_in=100,
        tokens_out=50,
        cost_usd=0.001,
        latency_ms=500,
    )
    return gateway

def test_pipeline_with_two_stage_classification(mock_gateway, tmp_path):
    '''Test full pipeline: ingest → filter → classify → route → memory'''
    # Setup
    memory = SqlMemory(f'sqlite:///{tmp_path}/test.db')
    # ... configure test brand, mock source ...
    
    pipeline = Pipeline(brand_cfg, gateway=mock_gateway, memory=memory)
    stats = pipeline.run_once()
    
    # Verify filter stage was called
    assert mock_gateway.complete.call_args_list[0][1]['stage'] == 'filter'
    # Verify classify stage was called for passed signals
    assert mock_gateway.complete.call_args_list[1][1]['stage'] == 'classify'
    # Verify llm_calls recorded
    llm_calls = memory.query_llm_calls(brand_slug='test')
    assert len(llm_calls) >= 2
```

2. Add tests for:
   - Filter rejects off-brand signal (only 1 LLM call)
   - Full classification path (2 LLM calls)
   - Routing tiebreaker triggered (3 LLM calls)
   - Gateway fallback on error
   - Cost tracking accuracy

3. Create `tests/integration/test_model_swap.py`:
   - Test switching models.yaml and verifying new model is used

4. Add smoke test that runs against real OpenRouter (skipped by default, enabled via env var)

**Test Strategy:**

Run integration test suite:
- All tests pass with mocked gateway
- Optional smoke test passes with real OpenRouter API
- Test coverage for gateway integration >80%
- Performance: full test suite runs in <30 seconds
