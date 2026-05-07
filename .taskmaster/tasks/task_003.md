# Task ID: 3

**Title:** Add llm_calls Table for Audit Trail

**Status:** done

**Dependencies:** 1 ✓

**Priority:** high

**Description:** Extend the database schema to track every LLM invocation with stage, model, tokens, cost, and latency for cost dashboards and debugging.

**Details:**

1. Add `LLMCallRow` to `src/resound/memory/__init__.py`:
```python
class LLMCallRow(Base):
    __tablename__ = "llm_calls"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_slug: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)  # filter/classify/routing_tiebreaker/memory_query
    model: Mapped[str] = mapped_column(String(128), index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 of prompt for dedup analysis
    response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    latency_ms: Mapped[int] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    called_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
```

2. Add `record_llm_call()` method to `SqlMemory`:
```python
def record_llm_call(self, brand_slug: str, response: LLMResponse, stage: str, prompt: str, success: bool = True, error: str | None = None) -> int
```

3. Add query methods to `SqlMemory`:
   - `query_llm_costs(brand_slug: str, since: datetime) -> list[dict]` - aggregate costs by stage and model
   - `query_llm_latency(brand_slug: str, since: datetime) -> dict` - p50/p95 latency by stage
   - `query_fallback_rate(brand_slug: str, since: datetime) -> dict` - count of fallback triggers by stage

4. Create Alembic migration for the new table under `src/resound/memory/migrations/`

**Test Strategy:**

Unit tests:
- Test `record_llm_call()` persists all fields correctly
- Test `query_llm_costs()` correctly aggregates by stage and model
- Test `query_llm_latency()` computes correct p50/p95 percentiles
- Test `query_fallback_rate()` counts primary vs fallback model usage
- Test Alembic migration applies and rolls back cleanly

## Subtasks

### 3.1. Add LLMCallRow ORM model to memory module

**Status:** done  
**Dependencies:** None  

Add the llm_calls table schema to src/resound/memory/__init__.py. No Alembic â€” relies on existing Base.metadata.create_all() pattern.

**Details:**

DESIGN LOCKED via grilling on 2026-05-05 (see docs/design_decisions.md #26, #27, #30).

File: src/resound/memory/__init__.py

Add this class before the SqlMemory class definition (after FeedbackRow, around line 110):

class LLMCallRow(Base):
    __tablename__ = llm_calls

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_slug: Mapped[str] = mapped_column(String(64), index=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey(signals.id), nullable=True, index=True,
    )  # nullable: memory_query has no signal context (per #27)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    # values: filter | classify | routing_tiebreaker | memory_query

    # nullable model: failure-before-any-call rows (e.g., LLMGatewayConfigError) have no model
    model: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    # SHA-256 of the assembled prompt â€” supports are

### 3.2. Amend LLMResponse: add was_fallback and attempt_count fields

**Status:** done  
**Dependencies:** None  

Add 2 fields to LLMResponse that the audit trail needs (Task 1 amendment per #29). Update OpenRouterGateway.complete() to set them based on retry/fallback orchestration outcome.

**Details:**

DESIGN LOCKED via grilling on 2026-05-05 (see docs/design_decisions.md #29 â€” amends Task 1 #11).

CONTEXT: Task 3 needs to know did

### 3.3. Implement record_llm_call and record_llm_failure on SqlMemory

**Status:** done  
**Dependencies:** None  

Add the two writer methods to SqlMemory. Split by success vs failure to avoid conditional logic everywhere (per #28).

**Details:**

DESIGN LOCKED via grilling on 2026-05-05 (see docs/design_decisions.md #28, #29, #30).

File: src/resound/memory/__init__.py

Depends on subtask 3.1 (LLMCallRow exists) and 3.2 (LLMResponse has was_fallback + attempt_count).

Add these two methods to SqlMemory class, in the writes section (after record_feedback, around line 191). Both use keyword-only args after the leading positional brand_slug:

import hashlib
from resound.gateway import LLMResponse, LLMGatewayError

def record_llm_call(
    self,
    *,
    brand_slug: str,
    stage: str,
    prompt: str,
    response: LLMResponse,
    was_fallback: bool,
    attempt_count: int,
    signal_id: int | None = None,
) -> int:
    "Record

### 3.4. Implement query_llm_costs / query_llm_latency / query_fallback_rate

**Status:** done  
**Dependencies:** None  

Add the three query methods to SqlMemory for the LLM telemetry dashboard. Python-side percentile computation; required since param.

**Details:**

DESIGN LOCKED via grilling on 2026-05-05 (see docs/design_decisions.md #32, #33, #34).

File: src/resound/memory/__init__.py

Depends on subtask 3.1 (LLMCallRow exists). Add to the reads section (after query_recent, around line 222).

from sqlalchemy import func

def query_llm_costs(
    self,
    brand_slug: str,
    since: datetime,
) -> list[dict[str, Any]]:
    "Aggregate

### 3.5. Add unit tests for LLMCallRow writers and queries

**Status:** done  
**Dependencies:** None  

Comprehensive test suite for record_llm_call, record_llm_failure, and the three query methods using in-memory SQLite for speed and isolation.

**Details:**

DESIGN LOCKED via grilling on 2026-05-05 (see docs/design_decisions.md #32 for percentile testing notes).

Depends on subtasks 3.1, 3.2, 3.3, 3.4.

File: tests/memory/test_llm_calls.py (create new file; create tests/memory/ if missing).

Test cases (use pytest, sqlite:///:memory: for isolation):

CLASS: TestRecordLlmCall (success path)
- test_records_all_fields_from_response: construct LLMResponse with known values, call record_llm_call, query back the row, assert every column matches.
- test_signal_id_optional: omit signal_id, row has signal_id=None.
- test_signal_id_set: pass signal_id=42, row has signal_id=42.
- test_was_fallback_persisted: pass was_fallback=True, row has was_fallback=True.
- test_attempt_count_persisted: pass attempt_count=4, row has attempt_count=4.
- test_prompt_hash_is_sha256: assert returned row prompt_hash matches manually computed sha256(prompt).
- test_response_content_persisted: response.content is stored verbatim.
- test_cost_usd_none_persists_as_null: LLMResponse.cost_usd=None persists as NULL (per Task 1 #7).

CLASS: TestRecordLlmFailure
- test_records_error_class_and_message: pass LLMGatewayTimeoutError(budget
