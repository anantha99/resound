"""Layer 2: Understanding. Every classifier produces a Classification."""

from __future__ import annotations

from abc import ABC, abstractmethod

from resound.models import Classification, RawSignal


class Classifier(ABC):
    """Decides if a signal is relevant, what it's about, how serious it is,
    and what action class it warrants.

    The brand_context is a free-form text block (typically markdown) loaded
    from brands/<brand>/understanding.md. It tells the classifier the brand's
    taxonomy, glossary, and any examples.
    """

    @abstractmethod
    def classify(self, raw: RawSignal, brand_context: str) -> Classification:
        ...
