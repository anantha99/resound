# Creates the 5 subtasks for Task 3 (llm_calls audit trail) with locked
# design decisions from the 2026-05-05 grilling session baked into --details
# at creation time. Uses add-subtask (a pure structural CLI op, no AI
# subprocess) to avoid the spawn-claude problem we hit with update-subtask.
#
# RUN THIS FROM A SEPARATE TERMINAL (outside an active Claude Code session)
# in case any task-master CLI path still spawns child claude processes.
#
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File .taskmaster/scripts/apply-task3-grilling.ps1
#
# NOT idempotent: re-running creates duplicate subtasks. Run exactly once.
# Verify with: task-master show 3
#
# Note: subtask 3.2 amends Task 1 code (LLMResponse + OpenRouterGateway).
# This is intentional — see docs/design_decisions.md #29 for the rationale.
# The amendment lands in Task 3's PR because Task 3 is the consumer that
# needs the new fields; Task 1 already shipped without them.
#
# Authoritative spec: docs/design_decisions.md (Task 3 section, decisions #26-#34).

$ErrorActionPreference = 'Stop'

# ----------------------------------------------------------------------------
# Subtask 3.1 — Add LLMCallRow schema
# ----------------------------------------------------------------------------

$title_3_1 = 'Add LLMCallRow ORM model to memory module'

$desc_3_1 = 'Add the llm_calls table schema to src/resound/memory/__init__.py. No Alembic — relies on existing Base.metadata.create_all() pattern.'

$details_3_1 = @'
DESIGN LOCKED via grilling on 2026-05-05 (see docs/design_decisions.md #26, #27, #30).

File: src/resound/memory/__init__.py

Add this class before the SqlMemory class definition (after FeedbackRow, around line 110):

class LLMCallRow(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_slug: Mapped[str] = mapped_column(String(64), index=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id"), nullable=True, index=True,
    )  # nullable: memory_query has no signal context (per #27)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    # values: filter | classify | routing_tiebreaker | memory_query

    # nullable model: failure-before-any-call rows (e.g., LLMGatewayConfigError) have no model
    model: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    # SHA-256 of the assembled prompt — supports "are we deduping" metric

    response_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # verbatim LLMResponse.content; nullable on failure rows (per #30)

    # token/cost fields nullable on failure rows
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    latency_ms: Mapped[int] = mapped_column(Integer)  # always set, even on timeout

    success: Mapped[bool] = mapped_column(Boolean, index=True)

    # fallback orchestration metadata (per #29)
    was_fallback: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)

    # error context for failure rows (per #28)
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # e.g., "LLMGatewayTimeoutError"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    called_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True,
    )

CRITICAL constraints from the grilling:

1. NO Alembic migration. The existing Base.metadata.create_all(self.engine) call at line 118 will create this table on next SqlMemory instantiation. No migrations/ directory, no alembic.ini, no version files. This is deliberate per #26.

2. signal_id is NULLABLE with no cascade — memory_query has no signal context, and we want audit rows to survive signal deletion. ForeignKey("signals.id") only, no ondelete= argument.

3. Do NOT add a response_hash column. Plan originally had one; #30 dropped it (no real use case — responses are not deduped, prompts are).

4. Do NOT add a prompt text column. Signal content is in signals.content; system prompts are static templates (#30).

5. Do NOT add a raw_response JSON column. Heavy and demo-unneeded (#30). Production deployment can add it later via a one-line schema change.

6. The cost_usd nullability matches Task 1 #7 (OpenRouter does not always return usage.cost; missing values become None).

Acceptance criteria:
- Class definition added per spec.
- All necessary imports already present in the file (verified Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Mapped, mapped_column).
- Instantiating SqlMemory() against a fresh SQLite file creates the llm_calls table without error.
- Manual smoke check: select * from sqlite_master where name="llm_calls" returns the table with all expected columns.
- No code changes to existing tables (signals, classifications, routes, feedback_events).
'@

# ----------------------------------------------------------------------------
# Subtask 3.2 — Amend LLMResponse + OpenRouterGateway (Task 1 amendment)
# ----------------------------------------------------------------------------

$title_3_2 = 'Amend LLMResponse: add was_fallback and attempt_count fields'

$desc_3_2 = 'Add 2 fields to LLMResponse that the audit trail needs (Task 1 amendment per #29). Update OpenRouterGateway.complete() to set them based on retry/fallback orchestration outcome.'

$details_3_2 = @'
DESIGN LOCKED via grilling on 2026-05-05 (see docs/design_decisions.md #29 — amends Task 1 #11).

CONTEXT: Task 3 needs to know "did fallback fire?" and "how many attempts?" to populate was_fallback and attempt_count columns in LLMCallRow. Task 1 #11 deliberately kept LLMResponse lean and excluded per-attempt history. These two new fields are AGGREGATE SCALARS, not per-attempt arrays — they stay within the spirit of #11 while giving the audit trail what it needs without lossy joins against current ModelsConfig.

CHANGES:

1. File: src/resound/gateway/base.py
   Add 2 fields to LLMResponse Pydantic model:

   class LLMResponse(BaseModel):
       content: str
       model_used: str
       tokens_in: int
       tokens_out: int
       cost_usd: float | None
       latency_ms: float
       raw_response: dict[str, Any]
       was_fallback: bool = False    # NEW: True if model_used != stage primary
       attempt_count: int = 1         # NEW: total attempts incl. retries + fallback hops

2. File: src/resound/gateway/openrouter.py
   In OpenRouterGateway.complete(), track these during the retry/fallback loop:
   - was_fallback = (model_used != stage_config.model)
     (i.e., true whenever the winning model is anything other than the stage's primary)
   - attempt_count = total request attempts across all retries and fallback hops, including the successful one
     (e.g., primary failed twice with 5xx then succeeded on retry 3 = attempt_count 3;
      primary failed all 3 retries then fallback succeeded on attempt 1 = attempt_count 4)

   Pass both into LLMResponse(...) when constructing the success-path return value.

CRITICAL constraints:

1. Defaults MUST be was_fallback=False and attempt_count=1. This means existing test code that constructs LLMResponse without these fields keeps working — it implicitly says "single successful attempt on the primary model."

2. Do NOT expose attempts (per-attempt array) on LLMResponse — that would substantively reopen Task 1 #11. The list[tuple[str, Exception]] still lives ONLY on LLMGatewayExhaustedError per Task 1 #13.

3. attempt_count counts REQUEST ATTEMPTS, not retries-from-zero. A success on the very first request = 1, not 0.

4. was_fallback is computed by string equality model_used == stage_config.model. If the primary returned successfully (even after retries), was_fallback is False. Only fallback-model wins set it to True.

5. Update the gateway's unit tests to assert these fields in:
   - happy path (was_fallback=False, attempt_count=1)
   - retried-success path (was_fallback=False, attempt_count=2 or 3)
   - fallback-success path (was_fallback=True, attempt_count=4+)

Acceptance criteria:
- LLMResponse pydantic model has 9 fields (was 7).
- OpenRouterGateway.complete() success path sets both fields correctly across primary-success, retried-success, fallback-success scenarios.
- Existing tests pass (defaults preserve old behavior).
- New test cases assert was_fallback / attempt_count in the three scenarios above.
- docs/design_decisions.md decision #11 already updated with the amendment note (no further doc work needed in this subtask).
'@

# ----------------------------------------------------------------------------
# Subtask 3.3 — Implement writer methods on SqlMemory
# ----------------------------------------------------------------------------

$title_3_3 = 'Implement record_llm_call and record_llm_failure on SqlMemory'

$desc_3_3 = 'Add the two writer methods to SqlMemory. Split by success vs failure to avoid conditional logic everywhere (per #28).'

$details_3_3 = @'
DESIGN LOCKED via grilling on 2026-05-05 (see docs/design_decisions.md #28, #29, #30).

File: src/resound/memory/__init__.py

Depends on subtask 3.1 (LLMCallRow exists) and 3.2 (LLMResponse has was_fallback + attempt_count).

Add these two methods to SqlMemory class, in the "writes" section (after record_feedback, around line 191). Both use keyword-only args after the leading positional brand_slug:

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
    """Record a successful LLM gateway call (the gateway returned an LLMResponse).

    See docs/design_decisions.md #28 for why this is split from record_llm_failure.
    """
    with Session(self.engine) as s:
        row = LLMCallRow(
            brand_slug=brand_slug,
            signal_id=signal_id,
            stage=stage,
            model=response.model_used,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            response_content=response.content,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
            latency_ms=int(response.latency_ms),
            success=True,
            was_fallback=was_fallback,
            attempt_count=attempt_count,
            error_class=None,
            error_message=None,
        )
        s.add(row)
        s.commit()
        return row.id

def record_llm_failure(
    self,
    *,
    brand_slug: str,
    stage: str,
    prompt: str,
    error: LLMGatewayError,
    latency_ms: int,
    attempt_count: int,
    signal_id: int | None = None,
) -> int:
    """Record a failed LLM gateway call (gateway raised before producing a response).

    Failure rows have model=None when no attempt reached a model (e.g., LLMGatewayConfigError),
    or the last attempted model name when known (e.g., LLMGatewayExhaustedError carries attempts).
    See docs/design_decisions.md #28.
    """
    last_model: str | None = None
    if hasattr(error, "attempts") and error.attempts:
        last_model = error.attempts[-1][0]

    with Session(self.engine) as s:
        row = LLMCallRow(
            brand_slug=brand_slug,
            signal_id=signal_id,
            stage=stage,
            model=last_model,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            response_content=None,
            tokens_in=None,
            tokens_out=None,
            cost_usd=None,
            latency_ms=latency_ms,
            success=False,
            was_fallback=False,  # not meaningful on failure
            attempt_count=attempt_count,
            error_class=type(error).__name__,
            error_message=str(error),
        )
        s.add(row)
        s.commit()
        return row.id

CRITICAL constraints from the grilling:

1. Both methods are keyword-only after the leading args (the * separator). Call sites are explicit about every field — no positional arg confusion when call sites grow.

2. signal_id defaults to None to make memory_query callers ergonomic (they have no signal to associate).

3. prompt_hash is SHA-256 of the full assembled prompt (system + user). Compute it inside the writer; do NOT make the caller hash. Single source of truth for the hash algorithm.

4. record_llm_failure does NOT take success or was_fallback — both are implicit (success=False always; was_fallback is meaningless on failure). Hardcoded in the row construction.

5. record_llm_failure tries to extract last_model from LLMGatewayExhaustedError.attempts (which carries [(model, exc), ...] per Task 1 #13). For other error types (Timeout, Parse, Config, Auth), attempts is absent and last_model stays None. Use hasattr check rather than isinstance to avoid hard import dependencies on every error subclass.

6. Both methods return the new row id (matches existing record_signal/record_classification/record_route pattern).

Acceptance criteria:
- Both methods present, keyword-only signatures match exactly.
- Call to record_llm_call with valid LLMResponse persists all fields and returns int row id.
- Call to record_llm_failure with LLMGatewayExhaustedError persists last_model from attempts list.
- Call to record_llm_failure with LLMGatewayTimeoutError persists model=None.
- prompt_hash is reproducible (same prompt → same hash) and 64 chars hex.
- Test against fresh in-memory SQLite (sqlite:///:memory:) to keep tests fast and isolated.
'@

# ----------------------------------------------------------------------------
# Subtask 3.4 — Implement query methods on SqlMemory
# ----------------------------------------------------------------------------

$title_3_4 = 'Implement query_llm_costs / query_llm_latency / query_fallback_rate'

$desc_3_4 = 'Add the three query methods to SqlMemory for the LLM telemetry dashboard. Python-side percentile computation; required since param.'

$details_3_4 = @'
DESIGN LOCKED via grilling on 2026-05-05 (see docs/design_decisions.md #32, #33, #34).

File: src/resound/memory/__init__.py

Depends on subtask 3.1 (LLMCallRow exists). Add to the "reads" section (after query_recent, around line 222).

from sqlalchemy import func

def query_llm_costs(
    self,
    brand_slug: str,
    since: datetime,
) -> list[dict[str, Any]]:
    """Aggregate LLM costs by stage and model since the given datetime.

    Returns: list of dicts with keys {stage, model, total_cost_usd, total_tokens_in,
    total_tokens_out, call_count}. Excludes failure rows (success=False) since they
    have null cost. Caller passes explicit since (per #33 — no defaults).
    """
    with Session(self.engine) as s:
        stmt = (
            select(
                LLMCallRow.stage,
                LLMCallRow.model,
                func.sum(LLMCallRow.cost_usd).label("total_cost_usd"),
                func.sum(LLMCallRow.tokens_in).label("total_tokens_in"),
                func.sum(LLMCallRow.tokens_out).label("total_tokens_out"),
                func.count().label("call_count"),
            )
            .where(LLMCallRow.brand_slug == brand_slug)
            .where(LLMCallRow.called_at >= since)
            .where(LLMCallRow.success.is_(True))
            .group_by(LLMCallRow.stage, LLMCallRow.model)
            .order_by(LLMCallRow.stage, func.sum(LLMCallRow.cost_usd).desc())
        )
        return [
            {
                "stage": stage,
                "model": model,
                "total_cost_usd": float(total_cost or 0.0),
                "total_tokens_in": int(tin or 0),
                "total_tokens_out": int(tout or 0),
                "call_count": int(count),
            }
            for stage, model, total_cost, tin, tout, count in s.execute(stmt)
        ]

def query_llm_latency(
    self,
    brand_slug: str,
    since: datetime,
) -> dict[str, dict[str, Any]]:
    """Per-stage p50/p95/p99 latency in milliseconds, plus call count.

    Returns: {stage: {p50: ms, p95: ms, p99: ms, count: n}, ...}.
    Computed Python-side because SQLite has no native percentile (per #32).
    Excludes failures (timeouts capped at 30s would skew p95).

    For high-volume Postgres production, swap to dialect-aware percentile_cont:
      SELECT stage, percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50, ...
      FROM llm_calls WHERE brand_slug=:b AND called_at >= :s AND success=TRUE
      GROUP BY stage
    """
    with Session(self.engine) as s:
        stmt = (
            select(LLMCallRow.stage, LLMCallRow.latency_ms)
            .where(LLMCallRow.brand_slug == brand_slug)
            .where(LLMCallRow.called_at >= since)
            .where(LLMCallRow.success.is_(True))
        )
        by_stage: dict[str, list[int]] = {}
        for stage, latency in s.execute(stmt):
            by_stage.setdefault(stage, []).append(int(latency))

    out: dict[str, dict[str, Any]] = {}
    for stage, latencies in by_stage.items():
        latencies.sort()
        n = len(latencies)
        out[stage] = {
            "p50": latencies[int(n * 0.50)] if n else 0,
            "p95": latencies[min(int(n * 0.95), n - 1)] if n else 0,
            "p99": latencies[min(int(n * 0.99), n - 1)] if n else 0,
            "count": n,
        }
    return out

def query_fallback_rate(
    self,
    brand_slug: str,
    since: datetime,
) -> dict[str, dict[str, Any]]:
    """Per-stage fallback rate: count of was_fallback=True over total successful calls.

    Returns: {stage: {fallback_count: n, total_count: n, fallback_rate: float}, ...}.
    Excludes failures (was_fallback is meaningless on failure rows per #28).
    Trivially queryable now that was_fallback is a column (per #29).
    """
    with Session(self.engine) as s:
        stmt = (
            select(
                LLMCallRow.stage,
                func.sum(
                    func.cast(LLMCallRow.was_fallback, Integer)
                ).label("fallback_count"),
                func.count().label("total_count"),
            )
            .where(LLMCallRow.brand_slug == brand_slug)
            .where(LLMCallRow.called_at >= since)
            .where(LLMCallRow.success.is_(True))
            .group_by(LLMCallRow.stage)
        )
        out: dict[str, dict[str, Any]] = {}
        for stage, fb_count, total in s.execute(stmt):
            fb_count = int(fb_count or 0)
            total = int(total)
            out[stage] = {
                "fallback_count": fb_count,
                "total_count": total,
                "fallback_rate": (fb_count / total) if total else 0.0,
            }
        return out

CRITICAL constraints from the grilling:

1. since is REQUIRED on every method — no defaults like "last 24h" (#33). Caller passes explicit datetime.

2. All three methods FILTER OUT FAILURES (success.is_(True)). Latency stats are skewed by 30s timeouts; cost stats are meaningless on null-cost failures; fallback rate is undefined on failures. Failure analysis gets its own future query method if needed.

3. Percentile computation is Python-side using sorted-slice indices (#32). Use min(int(n * 0.99), n - 1) to avoid IndexError when n is small. Cross-DB-portable; demo data fits comfortably in memory.

4. Use func.cast(was_fallback, Integer) for the SUM in query_fallback_rate — SQLite stores Boolean as 0/1 internally, but explicit cast keeps the SQL portable to Postgres where Boolean SUM behavior differs.

5. Do NOT pre-build a query_llm_costs_by_day or query_llm_costs_by_hour for sparklines. Per #34, defer that to Task 7 if Task 7's dashboard needs it.

6. The list[dict] return for costs vs dict-of-dicts return for latency/fallback is intentional — costs has 2 group keys (stage + model) so a flat list is cleaner; latency/fallback have 1 group key (stage) so dict-keyed-by-stage is cleaner.

Acceptance criteria:
- All three methods present with exact signatures.
- query_llm_costs aggregates correctly: insert N rows for stage="classify" model="X" with known costs, sum matches.
- query_llm_latency p50/p95/p99: insert known latencies (e.g., 100, 200, 300, ..., 1000ms) for one stage, percentiles match expected indices (handle empty stage edge case).
- query_fallback_rate: insert mix of was_fallback=True/False rows, computed rate matches.
- All three exclude success=False rows from results.
- All three return empty dicts/lists when no rows match (no exceptions).
'@

# ----------------------------------------------------------------------------
# Subtask 3.5 — Unit tests
# ----------------------------------------------------------------------------

$title_3_5 = 'Add unit tests for LLMCallRow writers and queries'

$desc_3_5 = 'Comprehensive test suite for record_llm_call, record_llm_failure, and the three query methods using in-memory SQLite for speed and isolation.'

$details_3_5 = @'
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
- test_records_error_class_and_message: pass LLMGatewayTimeoutError("budget exceeded"), row has error_class="LLMGatewayTimeoutError" and error_message containing the text.
- test_extracts_last_model_from_exhausted_error: pass LLMGatewayExhaustedError(attempts=[("anthropic/claude-sonnet-4-6", exc1), ("openai/gpt-4.1", exc2)]), row has model="openai/gpt-4.1".
- test_no_attempts_means_null_model: pass LLMGatewayConfigError (no attempts attribute), row has model=None.
- test_success_is_false: every failure row has success=False.
- test_was_fallback_is_false_on_failure: every failure row has was_fallback=False.
- test_token_and_cost_fields_null: tokens_in, tokens_out, cost_usd all None on failure rows.
- test_response_content_null: response_content is NULL on failure rows.
- test_latency_ms_required_and_persisted: latency_ms is set even on timeout failures.

CLASS: TestQueryLlmCosts
- test_aggregates_by_stage_and_model: insert rows for (classify, modelA) and (classify, modelB), assert two rows returned grouped correctly.
- test_excludes_failures: insert one success row (cost=$0.01) and one failure row (cost=NULL); aggregation only includes the success.
- test_filters_by_brand_slug: rows for brand A and brand B; query for A returns only A rows.
- test_filters_by_since: rows older than `since` are excluded.
- test_empty_result: no rows in window returns empty list.

CLASS: TestQueryLlmLatency
- test_p50_p95_p99_indices: insert latencies [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000] for one stage; assert p50=600 (index 5), p95=1000 (index 9), p99=1000 (index 9, capped).
- test_excludes_failures: failure rows do not pollute latency stats.
- test_per_stage_isolation: insert rows for filter and classify with different latency distributions; each stage gets its own percentiles.
- test_empty_stage: no rows returns empty dict (NOT a dict with empty per-stage entries).
- test_single_row_does_not_crash: one row returns p50=p95=p99=that row's latency, count=1.

CLASS: TestQueryFallbackRate
- test_basic_rate: 7 success rows for "classify" with was_fallback distribution [F,F,F,T,T,F,T] returns {"classify": {"fallback_count": 3, "total_count": 7, "fallback_rate": 3/7}}.
- test_zero_fallbacks: all primary returns 0.0 rate, not division-by-zero.
- test_no_data_returns_empty_dict: no matching rows returns {} (not 0/0 entry).
- test_excludes_failures: failure rows excluded from both numerator and denominator.

CLASS: TestSchemaCreated (sanity check that #1 wiring works end-to-end)
- test_create_all_creates_llm_calls_table: instantiate SqlMemory(), assert table exists in sqlite_master.
- test_signal_id_foreign_key_enforced: insert row with valid signal_id, then with invalid signal_id (only on Postgres or with PRAGMA foreign_keys=ON; document if SQLite default is off).

CRITICAL constraints:

1. Use sqlite:///:memory: (in-memory SQLite) for ALL tests — fast, isolated, no cleanup needed.

2. Each test should construct its own SqlMemory() instance (or use a pytest fixture that does so per-test). DO NOT share state across tests.

3. Tests use real LLMResponse and real LLMGatewayError instances (no mocks for these — they are simple Pydantic / Exception classes, instantiate them with real values).

4. Tests for record_llm_call DO NOT depend on the gateway actually being called. The gateway is not under test here — the writer is. Construct LLMResponse(...) directly with known field values.

5. Use freezegun or pass explicit called_at if testing the since filter relies on specific timestamps. Do NOT use time.sleep.

6. Tests must run on Windows (the user's platform per environment) — no POSIX-only path tricks.

Acceptance criteria:
- All test cases above pass.
- pytest collection includes the new file (tests/memory/test_llm_calls.py).
- Test runtime under 5 seconds total (in-memory SQLite makes this trivial).
- No test depends on network, OpenRouter API, or actual gateway calls.
- Coverage report shows record_llm_call, record_llm_failure, query_llm_costs, query_llm_latency, query_fallback_rate at 100% line coverage.
'@

# ----------------------------------------------------------------------------
# Execute
# ----------------------------------------------------------------------------

$subtasks = @(
    @{ title = $title_3_1; description = $desc_3_1; details = $details_3_1 },
    @{ title = $title_3_2; description = $desc_3_2; details = $details_3_2 },
    @{ title = $title_3_3; description = $desc_3_3; details = $details_3_3 },
    @{ title = $title_3_4; description = $desc_3_4; details = $details_3_4 },
    @{ title = $title_3_5; description = $desc_3_5; details = $details_3_5 }
)

$index = 0
foreach ($s in $subtasks) {
    $index++
    Write-Host "==> Creating subtask 3.$index : $($s.title)" -ForegroundColor Cyan
    task-master add-subtask `
        --parent=3 `
        --title=$($s.title) `
        --description=$($s.description) `
        --details=$($s.details)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED creating subtask 3.$index (exit $LASTEXITCODE). Stopping." -ForegroundColor Red
        Write-Host "If --details is not a recognized flag in your task-master version, edit this script" -ForegroundColor Yellow
        Write-Host "to drop --details and re-run, then use update-subtask separately to add the design notes." -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "All 5 subtasks created. Verify with: task-master show 3" -ForegroundColor Green
Write-Host "Authoritative design spec: docs/design_decisions.md (Task 3 section, decisions #26-#34)" -ForegroundColor Gray
Write-Host "Note: subtask 3.2 amends Task 1 code (LLMResponse + OpenRouterGateway) per #29" -ForegroundColor Yellow
