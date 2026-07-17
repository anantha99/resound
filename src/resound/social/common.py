"""Provider-neutral cap allocation and exact Decimal budget controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

from resound.social.contracts import CanonicalIdentity, sha256_value


def provider_native_identity(value: str) -> CanonicalIdentity:
    normalized = value.strip()
    if not normalized:
        raise ValueError("provider native identity cannot be empty")
    return CanonicalIdentity(kind="provider_native_id", value=normalized)


def fallback_identity(
    *,
    platform: str,
    content_kind: str,
    canonical_url: str,
    provider_timestamp: datetime,
    content: str,
) -> CanonicalIdentity:
    """Build the only allowed fallback identity from complete canonical fields."""

    normalized_url = canonical_url.strip()
    normalized_content = " ".join(content.split())
    if not all((platform.strip(), content_kind.strip(), normalized_url, normalized_content)):
        raise ValueError("fallback identity requires platform, kind, URL, and content")
    if provider_timestamp.tzinfo is None:
        raise ValueError("fallback identity requires an exact timezone-aware provider timestamp")
    value = sha256_value(
        {
            "platform": platform.strip().lower(),
            "content_kind": content_kind.strip().lower(),
            "canonical_url": normalized_url,
            "provider_timestamp": provider_timestamp.isoformat(),
            "content": normalized_content,
        }
    )
    return CanonicalIdentity(kind="fallback_identity_hash", value=value)


def allocate_signal_cap(path_caps: dict[str, int], source_cap: int) -> dict[str, int]:
    """Allocate a source signal ceiling proportionally and deterministically."""

    positive = {path: cap for path, cap in path_caps.items() if cap > 0}
    if source_cap < len(positive):
        raise ValueError("max_signals_per_source cannot allocate one row to every selected path")
    allocation = {path: 1 for path in positive}
    remaining = source_cap - len(positive)
    weights = {path: cap - 1 for path, cap in positive.items()}
    total_weight = sum(weights.values())
    if remaining and total_weight:
        for path in positive:
            extra = min(weights[path], (remaining * weights[path]) // total_weight)
            allocation[path] += extra
        remainder = min(source_cap, sum(positive.values())) - sum(allocation.values())
        while remainder:
            changed = False
            for path in positive:
                if allocation[path] < positive[path]:
                    allocation[path] += 1
                    remainder -= 1
                    changed = True
                    if not remainder:
                        break
            if not changed:
                break
    return allocation


def floor_to_quantum(value: Decimal, quantum: Decimal) -> Decimal:
    if quantum <= 0:
        raise ValueError("charge quantum must be greater than zero")
    return (value / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum


@dataclass(frozen=True)
class ActorStartReservation:
    reservation_id: str
    amount_usd: Decimal


@dataclass
class ProviderBudget:
    ceiling_usd: Decimal
    charge_quantum_usd: Decimal
    minimum_call_charge_usd: Decimal
    conservative_request_cost_usd: Decimal
    reconciled_spend_usd: Decimal = Decimal("0")
    reservations: dict[str, ActorStartReservation] = field(default_factory=dict)
    unresolved_start: bool = False

    def remaining_charge_cap(self) -> Decimal:
        reserved = sum((item.amount_usd for item in self.reservations.values()), Decimal("0"))
        return floor_to_quantum(
            self.ceiling_usd - self.reconciled_spend_usd - reserved,
            self.charge_quantum_usd,
        )

    def reserve(self, reservation_id: str) -> ActorStartReservation:
        if self.unresolved_start:
            raise RuntimeError("an actor start is unresolved; no later Run may start")
        remaining = self.remaining_charge_cap()
        required = max(self.minimum_call_charge_usd, self.conservative_request_cost_usd)
        if remaining < required:
            raise RuntimeError("remaining provider budget is below the safe call minimum")
        reservation = ActorStartReservation(reservation_id, remaining)
        self.reservations[reservation_id] = reservation
        self.unresolved_start = True
        return reservation

    def resolve_start(self, reservation_id: str) -> None:
        self.reservations.pop(reservation_id, None)
        self.unresolved_start = False

    def reconcile(self, reservation_id: str, usage_total_usd: Decimal) -> None:
        if usage_total_usd < 0:
            raise ValueError("usageTotalUsd cannot be negative")
        self.reconciled_spend_usd += usage_total_usd
        self.resolve_start(reservation_id)

