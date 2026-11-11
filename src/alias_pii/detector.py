"""The Alias detector (step 5): the rules and the fine-tuned model together.

Both run on the whole text and every span of both is kept (union); overlapping spans are merged
into one, typed after the strongest (`entities.resolve_overlaps`, as in masking). The rules bring
what a checksum or a keyword proves (IBAN, NIR, a date announced as a birth date); the model
brings what needs context (names, addresses, unannounced dates). A value either one finds is
masked: for Alias a missed value costs more than an extra one.
"""

from __future__ import annotations

from alias_pii.entities import Entity, resolve_overlaps
from alias_pii.masking import Detector
from alias_pii.rules import RuleDetector


class RulesAndModel:
    """`detect(text)`: union of the rules' and the model's spans, sorted and non-overlapping."""

    name = "rules+model"

    def __init__(self, model: Detector, rules: Detector | None = None):
        self.model = model
        self.rules = rules if rules is not None else RuleDetector()

    @classmethod
    def from_checkpoint(cls, path: str, **options) -> RulesAndModel:
        """The rules plus a fine-tuned checkpoint (`train.TrainedDetector` options)."""
        from alias_pii.train import TrainedDetector

        return cls(TrainedDetector(path, **options))

    def detect(self, text: str) -> list[Entity]:
        return resolve_overlaps(self.rules.detect(text) + self.model.detect(text))
