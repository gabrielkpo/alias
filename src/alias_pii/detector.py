"""The Alias detector (step 5): the rules and the fine-tuned model together.

Both run on the whole text; the model's spans are all kept, and the rules' spans of the types
they prove (`RULE_TYPES`: a checksum for IBANs and national IDs, a keyword for a birth date) are
added. Overlapping spans are merged into one, typed after the strongest
(`entities.resolve_overlaps`, as in masking), so nothing of an overlapped value stays in clear.

The rules' e-mails, phones and identifiers are left out: they also catch company mailboxes,
switchboards and invoice numbers, which the model learnt to leave in clear. Adding them dropped
the precision from 0.97 to 0.79 on the synthetic validation split for no leak gained there
(docs/DETECTOR.md).
"""

from __future__ import annotations

from collections.abc import Iterable

from alias_pii.entities import Entity, EntityType, resolve_overlaps
from alias_pii.masking import Detector
from alias_pii.rules import RuleDetector

RULE_TYPES = frozenset({EntityType.IBAN, EntityType.NATIONAL_ID, EntityType.BIRTH_DATE})

# Variant 3 (docs/DETECTOR.md): the rules' identifiers announced by a keyword naming a person's
# file. Orders, invoices, tickets, references and accounts are left out: on the validation
# splits the rule's precision after those keywords is near zero.
PERSON_FILE_KEYWORDS = frozenset(
    {
        "dossier", "contrat", "client", "patient", "adherent", "matricule", "sinistre",
        "passeport", "permis", "file", "claim", "customer", "passport", "licence", "license",
        "employee", "member", "membership",
    }
)  # fmt: skip


class RulesAndModel:
    """`detect(text)`: the model's spans plus the rules' spans of `rule_types` (all types when
    `rule_types` is None), sorted and non-overlapping."""

    name = "rules+model"

    def __init__(
        self,
        model: Detector,
        rules: Detector | None = None,
        rule_types: Iterable[EntityType] | None = RULE_TYPES,
        id_keywords: Iterable[str] | None = None,
    ):
        self.model = model
        self.rules = rules if rules is not None else RuleDetector()
        self.rule_types = frozenset(rule_types) if rule_types is not None else None
        # Identifiers from the rules are also kept when their keyword (`Entity.kind`) is here.
        self.id_keywords = frozenset(id_keywords or ())

    @classmethod
    def from_checkpoint(cls, path: str, **options) -> RulesAndModel:
        """The rules plus a fine-tuned checkpoint (`train.TrainedDetector` options)."""
        from alias_pii.train import TrainedDetector

        rule_types = options.pop("rule_types", RULE_TYPES)
        id_keywords = options.pop("id_keywords", None)
        return cls(TrainedDetector(path, **options), rule_types=rule_types, id_keywords=id_keywords)

    def _kept(self, entity: Entity) -> bool:
        if self.rule_types is None or entity.type in self.rule_types:
            return True
        return entity.type is EntityType.IDENTIFIER and entity.kind in self.id_keywords

    def detect(self, text: str) -> list[Entity]:
        rules = [e for e in self.rules.detect(text) if self._kept(e)]
        return resolve_overlaps(rules + self.model.detect(text))
