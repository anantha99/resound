"""Layer 2: Understanding. Every classifier produces a Classification."""

from __future__ import annotations

from abc import ABC, abstractmethod

from resound.gateway import LLMResponse
from resound.models import Classification, RawSignal


class Classifier(ABC):
    """Decides if a signal is relevant, what it's about, how serious it is,
    and what action class it warrants.

    The brand_context is a free-form text block (typically markdown) loaded
    from brands/<brand>/understanding.md. It tells the classifier the brand's
    taxonomy, glossary, and any examples.

    classify() returns a 2-tuple of (Classification, LLMResponse). The
    LLMResponse is consumed by Pipeline to write the llm_calls audit row.
    Gateway exceptions (LLMGatewayError and subclasses) propagate up to the
    Pipeline; parse failures return a stub Classification with the unparseable
    content preserved on the LLMResponse (see design_decisions.md #36, #40).
    """

    @abstractmethod
    def classify(
        self, raw: RawSignal, brand_context: str
    ) -> tuple[Classification, LLMResponse]:
        ...
