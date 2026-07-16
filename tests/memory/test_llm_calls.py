"""Tests for the ``llm_calls`` audit trail layer (Task 3).

Covers the writer split (decision #28), the schema (decisions #26-#30),
and the three query methods (decisions #32-#34). All tests use an
in-memory SQLite engine for isolation; each test gets a fresh ``SqlMemory``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from resound.gateway import (
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayExhaustedError,
    LLMGatewayTimeoutError,
    LLMResponse,
)
from resound.memory import LLMCallRow, SqlMemory


@pytest.fixture
def memory() -> SqlMemory:
    return SqlMemory(database_url="sqlite:///:memory:")


def _response(
    *,
    content: str = "ok",
    model: str = "openai/gpt-4.1-mini",
    tokens_in: int = 10,
    tokens_out: int = 5,
    cost_usd: float | None = 0.001,
    latency_ms: float = 123.4,
    was_fallback: bool = False,
    attempt_count: int = 1,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        raw_response={"id": "x"},
        was_fallback=was_fallback,
        attempt_count=attempt_count,
    )


def _row(memory: SqlMemory, row_id: int) -> LLMCallRow:
    with Session(memory.engine) as s:
        return s.execute(
            select(LLMCallRow).where(LLMCallRow.id == row_id)
        ).scalar_one()


# =============================================================================
# Writers (subtasks 3.1, 3.3)
# =============================================================================


class TestRecordLlmCall:
    def test_records_all_fields_from_response(self, memory: SqlMemory) -> None:
        r = _response(
            content='{"answer": 42}',
            model="anthropic/claude-sonnet-4-6",
            tokens_in=88,
            tokens_out=12,
            cost_usd=0.0042,
            latency_ms=512.5,
        )
        rid = memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt="hello world",
            response=r,
            was_fallback=False,
            attempt_count=1,
        )
        row = _row(memory, rid)
        assert row.brand_slug == "lq"
        assert row.stage == "classify"
        assert row.model == "anthropic/claude-sonnet-4-6"
        assert row.response_content == '{"answer": 42}'
        assert row.tokens_in == 88
        assert row.tokens_out == 12
        assert row.cost_usd == 0.0042
        assert row.latency_ms == 512.5
        assert row.success is True
        assert row.error_class is None
        assert row.error_message is None
        assert row.was_fallback is False
        assert row.attempt_count == 1

    def test_signal_id_optional(self, memory: SqlMemory) -> None:
        rid = memory.record_llm_call(
            brand_slug="lq",
            stage="memory_query",
            prompt="p",
            response=_response(),
            was_fallback=False,
            attempt_count=1,
        )
        assert _row(memory, rid).signal_id is None

    def test_signal_id_set(self, memory: SqlMemory) -> None:
        rid = memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            response=_response(),
            was_fallback=False,
            attempt_count=1,
            signal_id=42,
        )
        assert _row(memory, rid).signal_id == 42

    def test_was_fallback_persisted(self, memory: SqlMemory) -> None:
        rid = memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            response=_response(was_fallback=True),
            was_fallback=True,
            attempt_count=4,
        )
        row = _row(memory, rid)
        assert row.was_fallback is True

    def test_attempt_count_persisted(self, memory: SqlMemory) -> None:
        rid = memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            response=_response(),
            was_fallback=False,
            attempt_count=4,
        )
        assert _row(memory, rid).attempt_count == 4

    def test_prompt_hash_is_sha256(self, memory: SqlMemory) -> None:
        prompt = "the assembled prompt text"
        rid = memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt=prompt,
            response=_response(),
            was_fallback=False,
            attempt_count=1,
        )
        expected = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        assert _row(memory, rid).prompt_hash == expected
        assert len(expected) == 64

    def test_response_content_persisted_verbatim(
        self, memory: SqlMemory,
    ) -> None:
        long_text = '{"summary": "' + ("x" * 2000) + '"}'
        rid = memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            response=_response(content=long_text),
            was_fallback=False,
            attempt_count=1,
        )
        assert _row(memory, rid).response_content == long_text

    def test_cost_usd_none_persists_as_null(self, memory: SqlMemory) -> None:
        # Per design #7: OpenRouter sometimes omits usage.cost — null OK.
        rid = memory.record_llm_call(
            brand_slug="lq",
            stage="filter",
            prompt="p",
            response=_response(cost_usd=None),
            was_fallback=False,
            attempt_count=1,
        )
        assert _row(memory, rid).cost_usd is None

    def test_called_at_set_at_write(self, memory: SqlMemory) -> None:
        before = datetime.utcnow()
        rid = memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            response=_response(),
            was_fallback=False,
            attempt_count=1,
        )
        row = _row(memory, rid)
        assert before <= row.called_at <= datetime.utcnow()


class TestRecordLlmFailure:
    def test_records_error_class_and_message(self, memory: SqlMemory) -> None:
        err = LLMGatewayTimeoutError(
            "Stage 'classify' exceeded 30.0s wall-clock cap"
        )
        rid = memory.record_llm_failure(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            error=err,
            latency_ms=30000.0,
            attempt_count=4,
        )
        row = _row(memory, rid)
        assert row.success is False
        assert row.error_class == "LLMGatewayTimeoutError"
        assert "30.0s" in row.error_message

    def test_failure_columns_are_null(self, memory: SqlMemory) -> None:
        rid = memory.record_llm_failure(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            error=LLMGatewayConfigError("missing key"),
            latency_ms=5.0,
            attempt_count=1,
        )
        row = _row(memory, rid)
        assert row.model is None
        assert row.tokens_in is None
        assert row.tokens_out is None
        assert row.cost_usd is None
        assert row.response_content is None

    def test_failure_records_latency_and_attempts(
        self, memory: SqlMemory,
    ) -> None:
        rid = memory.record_llm_failure(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            error=LLMGatewayExhaustedError("done", attempts=6),
            latency_ms=12345.6,
            attempt_count=6,
        )
        row = _row(memory, rid)
        assert row.latency_ms == 12345.6
        assert row.attempt_count == 6
        assert row.was_fallback is False

    def test_failure_preserves_known_billable_usage(self, memory: SqlMemory) -> None:
        error = LLMGatewayExhaustedError(
            "invalid outputs",
            attempts=3,
            model_used="google/gemini-3.1-flash-lite",
            tokens_in=30,
            tokens_out=60,
            cost_usd=0.60,
            latency_ms=123.0,
        )
        rid = memory.record_llm_failure(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            error=error,
            latency_ms=999.0,
            attempt_count=3,
        )

        row = _row(memory, rid)
        assert row.model == "google/gemini-3.1-flash-lite"
        assert row.tokens_in == 30
        assert row.tokens_out == 60
        assert row.cost_usd == pytest.approx(0.60)
        assert row.latency_ms == 123.0

        costs = memory.query_llm_costs("lq", since=SINCE_FAR_PAST)
        assert costs[0]["total_cost_usd"] == pytest.approx(0.60)

    def test_failure_signal_id_optional(self, memory: SqlMemory) -> None:
        rid = memory.record_llm_failure(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            error=LLMGatewayAuthError("bad key"),
            latency_ms=3.0,
            attempt_count=1,
            signal_id=99,
        )
        assert _row(memory, rid).signal_id == 99

    def test_failure_prompt_hash_matches_success_hash(
        self, memory: SqlMemory,
    ) -> None:
        # Same prompt → same hash, regardless of success/failure path.
        prompt = "shared prompt"
        ok = memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt=prompt,
            response=_response(),
            was_fallback=False,
            attempt_count=1,
        )
        bad = memory.record_llm_failure(
            brand_slug="lq",
            stage="classify",
            prompt=prompt,
            error=LLMGatewayTimeoutError("t"),
            latency_ms=1.0,
            attempt_count=1,
        )
        assert _row(memory, ok).prompt_hash == _row(memory, bad).prompt_hash


# =============================================================================
# Queries (subtask 3.4)
# =============================================================================


SINCE_FAR_PAST = datetime(2020, 1, 1)


def _seed_costs(memory: SqlMemory) -> None:
    """Seed: 3 classify primary calls, 2 classify fallback calls,
    1 filter primary, 1 filter primary on a different brand, 1 failure."""
    # classify, primary, m1
    for cost in (0.001, 0.002, 0.003):
        memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            response=_response(model="m1", cost_usd=cost),
            was_fallback=False,
            attempt_count=1,
        )
    # classify, fallback, m2
    for cost in (0.05, 0.06):
        memory.record_llm_call(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            response=_response(model="m2", cost_usd=cost),
            was_fallback=True,
            attempt_count=2,
        )
    # filter, primary, mf
    memory.record_llm_call(
        brand_slug="lq",
        stage="filter",
        prompt="p",
        response=_response(model="mf", cost_usd=0.0001),
        was_fallback=False,
        attempt_count=1,
    )
    # other brand — should be excluded by brand filter
    memory.record_llm_call(
        brand_slug="other",
        stage="filter",
        prompt="p",
        response=_response(model="mf", cost_usd=0.999),
        was_fallback=False,
        attempt_count=1,
    )
    # failure — should be excluded from cost aggregates
    memory.record_llm_failure(
        brand_slug="lq",
        stage="classify",
        prompt="p",
        error=LLMGatewayTimeoutError("t"),
        latency_ms=30000.0,
        attempt_count=4,
    )


class TestQueryLlmCosts:
    def test_aggregates_by_stage_and_model(self, memory: SqlMemory) -> None:
        _seed_costs(memory)
        rows = memory.query_llm_costs("lq", since=SINCE_FAR_PAST)
        keyed = {(r["stage"], r["model"]): r for r in rows}
        assert (
            pytest.approx(keyed[("classify", "m1")]["total_cost_usd"], rel=1e-9)
            == 0.006
        )
        assert keyed[("classify", "m1")]["call_count"] == 3
        assert (
            pytest.approx(keyed[("classify", "m2")]["total_cost_usd"], rel=1e-9)
            == 0.11
        )
        assert keyed[("classify", "m2")]["call_count"] == 2
        assert keyed[("filter", "mf")]["call_count"] == 1

    def test_excludes_failures(self, memory: SqlMemory) -> None:
        _seed_costs(memory)
        rows = memory.query_llm_costs("lq", since=SINCE_FAR_PAST)
        # 5 classify successes total; failure must not show up as a row or
        # bump any call_count.
        classify_calls = sum(
            r["call_count"] for r in rows if r["stage"] == "classify"
        )
        assert classify_calls == 5

    def test_excludes_other_brands(self, memory: SqlMemory) -> None:
        _seed_costs(memory)
        rows = memory.query_llm_costs("lq", since=SINCE_FAR_PAST)
        for r in rows:
            assert r["total_cost_usd"] < 0.5  # 0.999 row from "other" excluded

    def test_excludes_rows_before_since(self, memory: SqlMemory) -> None:
        _seed_costs(memory)
        future = datetime.utcnow() + timedelta(hours=1)
        assert memory.query_llm_costs("lq", since=future) == []

    def test_null_cost_does_not_break_sum(self, memory: SqlMemory) -> None:
        memory.record_llm_call(
            brand_slug="lq",
            stage="filter",
            prompt="p",
            response=_response(cost_usd=None),
            was_fallback=False,
            attempt_count=1,
        )
        memory.record_llm_call(
            brand_slug="lq",
            stage="filter",
            prompt="p",
            response=_response(cost_usd=0.5),
            was_fallback=False,
            attempt_count=1,
        )
        rows = memory.query_llm_costs("lq", since=SINCE_FAR_PAST)
        filter_row = next(r for r in rows if r["stage"] == "filter")
        # Both rows counted; only the non-null contributes to sum.
        assert filter_row["call_count"] == 2
        assert filter_row["total_cost_usd"] == pytest.approx(0.5)

    def test_token_totals(self, memory: SqlMemory) -> None:
        memory.record_llm_call(
            brand_slug="lq",
            stage="filter",
            prompt="p",
            response=_response(tokens_in=100, tokens_out=20),
            was_fallback=False,
            attempt_count=1,
        )
        memory.record_llm_call(
            brand_slug="lq",
            stage="filter",
            prompt="p",
            response=_response(tokens_in=50, tokens_out=10),
            was_fallback=False,
            attempt_count=1,
        )
        rows = memory.query_llm_costs("lq", since=SINCE_FAR_PAST)
        filter_row = next(r for r in rows if r["stage"] == "filter")
        assert filter_row["total_tokens_in"] == 150
        assert filter_row["total_tokens_out"] == 30

    def test_empty_returns_empty_list(self, memory: SqlMemory) -> None:
        assert memory.query_llm_costs("lq", since=SINCE_FAR_PAST) == []


class TestQueryLlmLatency:
    def test_percentiles_ten_values(self, memory: SqlMemory) -> None:
        for lat in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
            memory.record_llm_call(
                brand_slug="lq",
                stage="classify",
                prompt="p",
                response=_response(latency_ms=float(lat)),
                was_fallback=False,
                attempt_count=1,
            )
        result = memory.query_llm_latency("lq", since=SINCE_FAR_PAST)
        assert result["classify"]["count"] == 10
        # nearest-rank: ceil(0.5*10)=5 → values[4]=50
        assert result["classify"]["p50"] == 50.0
        # nearest-rank: ceil(0.95*10)=10 → values[9]=100
        assert result["classify"]["p95"] == 100.0
        assert result["classify"]["p99"] == 100.0

    def test_excludes_failures(self, memory: SqlMemory) -> None:
        # 5 successful calls at 100ms.
        for _ in range(5):
            memory.record_llm_call(
                brand_slug="lq",
                stage="classify",
                prompt="p",
                response=_response(latency_ms=100.0),
                was_fallback=False,
                attempt_count=1,
            )
        # A 30s timeout failure must NOT skew p95.
        memory.record_llm_failure(
            brand_slug="lq",
            stage="classify",
            prompt="p",
            error=LLMGatewayTimeoutError("t"),
            latency_ms=30000.0,
            attempt_count=4,
        )
        result = memory.query_llm_latency("lq", since=SINCE_FAR_PAST)
        assert result["classify"]["count"] == 5
        assert result["classify"]["p95"] == 100.0  # not 30000

    def test_per_stage_keys(self, memory: SqlMemory) -> None:
        memory.record_llm_call(
            brand_slug="lq", stage="filter", prompt="p",
            response=_response(latency_ms=5.0),
            was_fallback=False, attempt_count=1,
        )
        memory.record_llm_call(
            brand_slug="lq", stage="classify", prompt="p",
            response=_response(latency_ms=500.0),
            was_fallback=False, attempt_count=1,
        )
        result = memory.query_llm_latency("lq", since=SINCE_FAR_PAST)
        assert set(result.keys()) == {"filter", "classify"}

    def test_empty_window_omits_stages(self, memory: SqlMemory) -> None:
        # No data → empty dict, NOT a NaN-laden zero-padded shell.
        assert memory.query_llm_latency("lq", since=SINCE_FAR_PAST) == {}

    def test_single_value_percentiles(self, memory: SqlMemory) -> None:
        memory.record_llm_call(
            brand_slug="lq", stage="classify", prompt="p",
            response=_response(latency_ms=42.0),
            was_fallback=False, attempt_count=1,
        )
        result = memory.query_llm_latency("lq", since=SINCE_FAR_PAST)
        assert result["classify"] == {
            "count": 1, "p50": 42.0, "p95": 42.0, "p99": 42.0,
        }


class TestQueryFallbackRate:
    def test_per_stage_breakdown(self, memory: SqlMemory) -> None:
        # 4 primary + 1 fallback on classify; 2 primary on filter.
        for _ in range(4):
            memory.record_llm_call(
                brand_slug="lq", stage="classify", prompt="p",
                response=_response(was_fallback=False),
                was_fallback=False, attempt_count=1,
            )
        memory.record_llm_call(
            brand_slug="lq", stage="classify", prompt="p",
            response=_response(was_fallback=True),
            was_fallback=True, attempt_count=2,
        )
        for _ in range(2):
            memory.record_llm_call(
                brand_slug="lq", stage="filter", prompt="p",
                response=_response(was_fallback=False),
                was_fallback=False, attempt_count=1,
            )
        result = memory.query_fallback_rate("lq", since=SINCE_FAR_PAST)
        assert result["classify"]["primary_count"] == 4
        assert result["classify"]["fallback_count"] == 1
        assert result["classify"]["primary_rate"] == pytest.approx(0.8)
        assert result["filter"]["primary_count"] == 2
        assert result["filter"]["fallback_count"] == 0
        assert result["filter"]["primary_rate"] == 1.0

    def test_excludes_failures(self, memory: SqlMemory) -> None:
        memory.record_llm_call(
            brand_slug="lq", stage="classify", prompt="p",
            response=_response(was_fallback=False),
            was_fallback=False, attempt_count=1,
        )
        memory.record_llm_failure(
            brand_slug="lq", stage="classify", prompt="p",
            error=LLMGatewayTimeoutError("t"),
            latency_ms=30000.0, attempt_count=4,
        )
        result = memory.query_fallback_rate("lq", since=SINCE_FAR_PAST)
        assert result["classify"]["primary_count"] == 1
        assert result["classify"]["fallback_count"] == 0

    def test_only_fallbacks(self, memory: SqlMemory) -> None:
        memory.record_llm_call(
            brand_slug="lq", stage="classify", prompt="p",
            response=_response(was_fallback=True),
            was_fallback=True, attempt_count=2,
        )
        result = memory.query_fallback_rate("lq", since=SINCE_FAR_PAST)
        assert result["classify"]["primary_rate"] == 0.0

    def test_empty_returns_empty_dict(self, memory: SqlMemory) -> None:
        assert memory.query_fallback_rate("lq", since=SINCE_FAR_PAST) == {}

    def test_brand_isolation(self, memory: SqlMemory) -> None:
        memory.record_llm_call(
            brand_slug="other", stage="classify", prompt="p",
            response=_response(was_fallback=True),
            was_fallback=True, attempt_count=2,
        )
        assert memory.query_fallback_rate("lq", since=SINCE_FAR_PAST) == {}
