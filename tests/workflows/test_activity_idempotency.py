from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from resound.memory import SignalRow, SqlMemory
from resound.models import ActionClass, Classification, RawSignal, Sentiment, Severity
from resound.workflows.signal_processing import SignalProcessingRequest, process_signal


class FakeClassifier:
    def __init__(self):
        self.calls = 0

    def classify(self, raw: RawSignal, brand_context: str):
        self.calls += 1
        return (
            Classification(
                is_about_brand=True,
                area="ops",
                sentiment=Sentiment.NEUTRAL,
                severity=Severity.MEDIUM,
                action_class=ActionClass.SPRINT,
                summary="Needs ops review",
                confidence=0.8,
            ),
            _fake_response(),
        )


def test_process_signal_activity_is_idempotent_for_duplicate_external_id(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'workflow.db'}")
    org_id = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org_id, "acme", "Acme")
    classifier = FakeClassifier()
    request = SignalProcessingRequest(
        brand_slug="acme",
        raw_signal=RawSignal(
            source="reddit",
            external_id="same-post",
            content="Shipping damage keeps happening.",
            posted_at=datetime.now(tz=UTC),
        ),
        brand_context="Acme sells things.",
        routing_config={"default_route": "#triage"},
        people_config={"channels": {"#triage": {"slack_channel": "#triage"}}},
        organization_id=org_id,
        brand_id=brand.id,
    )

    first = process_signal(request, memory=memory, classifier=classifier)
    second = process_signal(request, memory=memory, classifier=classifier)

    with memory.session() as session:
        signals = list(session.execute(select(SignalRow)).scalars())

    assert first.status == "processed"
    assert second.status == "duplicate"
    assert len(signals) == 1
    assert classifier.calls == 1


def _fake_response():
    from resound.gateway import LLMResponse

    return LLMResponse(
        content="{}",
        model_used="fake/test",
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.001,
        latency_ms=12.0,
        raw_response={},
        was_fallback=False,
        attempt_count=1,
    )
