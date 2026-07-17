from datetime import UTC, datetime
from decimal import Decimal

import pytest

from resound.social.common import (
    ProviderBudget,
    allocate_signal_cap,
    fallback_identity,
    floor_to_quantum,
    provider_native_identity,
)


def test_proportional_allocation_is_deterministic_in_input_path_order() -> None:
    assert allocate_signal_cap(
        {"official_discovery": 25, "mention_discovery": 25, "official_comments": 10},
        17,
    ) == {
        "official_discovery": 7,
        "mention_discovery": 7,
        "official_comments": 3,
    }


def test_decimal_budget_floors_reserves_and_blocks_unresolved_start() -> None:
    budget = ProviderBudget(
        ceiling_usd=Decimal("1.00"),
        charge_quantum_usd=Decimal("0.01"),
        minimum_call_charge_usd=Decimal("0.50"),
        conservative_request_cost_usd=Decimal("0.50"),
        reconciled_spend_usd=Decimal("0.333"),
    )
    assert floor_to_quantum(Decimal("0.667"), Decimal("0.01")) == Decimal("0.66")
    reservation = budget.reserve("run-1")
    assert reservation.amount_usd == Decimal("0.66")
    with pytest.raises(RuntimeError, match="unresolved"):
        budget.reserve("run-2")
    budget.reconcile("run-1", Decimal("0.25"))
    assert budget.reconciled_spend_usd == Decimal("0.583")


def test_canonical_identity_never_guesses_native_provenance() -> None:
    native = provider_native_identity("provider-123")
    fallback = fallback_identity(
        platform="X",
        content_kind="post",
        canonical_url="https://x.com/acme/status/1",
        provider_timestamp=datetime(2026, 7, 17, tzinfo=UTC),
        content="  Exact   provider content ",
    )
    assert native.kind == "provider_native_id"
    assert fallback.kind == "fallback_identity_hash"
    assert len(fallback.value) == 64
    with pytest.raises(ValueError, match="timezone-aware"):
        fallback_identity(
            platform="x",
            content_kind="post",
            canonical_url="https://x.com/acme/status/1",
            provider_timestamp=datetime(2026, 7, 17),
            content="content",
        )
