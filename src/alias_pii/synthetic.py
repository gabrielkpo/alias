"""Synthetic annotated documents, French and English, to train and validate detectors.

Each document comes from a template (a letter, an e-mail, a medical or bank note) whose slots are
filled with Faker values. The spans of personal data are known exactly, so the labels are free;
values that look personal but are not (an appointment date, an amount, a company) are left
unlabelled on purpose, so a model also learns what not to mask.

Synthetic text is too regular to measure real performance: it trains and validates, and the
real hand-annotated sets measure. Templates are split between train and validation, so a model
is never validated on a layout it was trained on.

Run:
    uv run --group data python -m alias_pii.synthetic --split train --n 2000 \\
        --out data/synthetic/train.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from alias_pii import quality
from alias_pii.entities import EntityType
from alias_pii.identities import IdentityFactory

LOCALES = {"fr": "fr_FR", "en_us": "en_US", "en_gb": "en_GB"}
SPLITS = ("train", "validation")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str


@dataclass
class Example:
    text: str
    spans: list[Span]
    language: str  # "fr" or "en"
    locale: str
    template: str
    negatives: list[Span] = field(default_factory=list)  # distractors placed on purpose


# --- templates --------------------------------------------------------------------------------
# {LABEL} slots are personal data and get a span; {date}, {amount}, {org}, {city} are distractors.
# The last two templates of each language are kept for validation.

FR_TEMPLATES = {
    "fr_letter": (
        "{city}, le {date}\n\nMadame, Monsieur,\n\nJe soussigné(e) {PERSON}, "
        "né(e) le {BIRTH_DATE}, demeurant {ADDRESS}, vous prie de bien vouloir trouver "
        "ci-joint mon dossier n° {IDENTIFIER}.\nVous pouvez me joindre au {PHONE} "
        "ou par courriel à {EMAIL}.\n\n"
        "Veuillez agréer mes salutations distinguées.\n{PERSON}"
    ),
    "fr_bank": (
        "Objet : changement de coordonnées bancaires\n\nBonjour,\nSuite à notre échange du {date}, "
        "merci de prélever désormais les {amount} mensuels sur le compte {IBAN} au nom de "
        "{PERSON}.\nRéférence client : {IDENTIFIER}.\nCordialement,\n{org}"
    ),
    "fr_medical": (
        "Compte rendu de consultation du {date}\nPatient : {PERSON}, né(e) le {BIRTH_DATE}\n"
        "N° de sécurité sociale : {NATIONAL_ID}\nAdresse : {ADDRESS}\n"
        "Motif : contrôle annuel. Prochain rendez-vous au cabinet de {city}."
    ),
    "fr_email": (
        "De : {EMAIL}\nÀ : {org_email}\nObjet : rendez-vous\n\nBonjour, je suis "
        "{PERSON} et je souhaite décaler mon rendez-vous du {date}. Mon numéro : {PHONE}.\nMerci !"
    ),
    "fr_hr": (
        "Fiche salarié — {org}\nNom : {PERSON}\nDate de naissance : {BIRTH_DATE}\n"
        "NIR : {NATIONAL_ID}\nIBAN : {IBAN}\nMatricule : {IDENTIFIER}\nEmbauche le {date}."
    ),
    "fr_insurance": (
        "Déclaration de sinistre n° {IDENTIFIER}\nL'assuré, {PERSON}, domicilié au {ADDRESS}, "
        "signale un dégât des eaux survenu le {date}. Contact : {PHONE}, {EMAIL}."
    ),
}

EN_TEMPLATES = {
    "en_letter": (
        "{city}, {date}\n\nDear Sir or Madam,\n\nMy name is {PERSON}, born on {BIRTH_DATE}, and I "
        "live at {ADDRESS}. Please find attached my file, reference {IDENTIFIER}.\nYou can reach "
        "me on {PHONE} or at {EMAIL}.\n\nYours faithfully,\n{PERSON}"
    ),
    "en_bank": (
        "Subject: new bank details\n\nHello,\nFurther to our call on {date}, please collect the "
        "monthly {amount} from account {IBAN}, held by {PERSON}.\nCustomer ID: {IDENTIFIER}.\n"
        "Kind regards,\n{org}"
    ),
    "en_medical": (
        "Consultation note, {date}\nPatient: {PERSON}, date of birth {BIRTH_DATE}\n"
        "{NATIONAL_ID_NAME}: {NATIONAL_ID}\nAddress: {ADDRESS}\n"
        "Reason: annual check-up. Next appointment at the {city} practice."
    ),
    "en_email": (
        "From: {EMAIL}\nTo: {org_email}\nSubject: appointment\n\nHi, this is {PERSON}. "
        "Could we move my appointment of {date}? My number is {PHONE}.\nThanks!"
    ),
    "en_hr": (
        "Employee record — {org}\nName: {PERSON}\nDate of birth: {BIRTH_DATE}\n"
        "{NATIONAL_ID_NAME}: {NATIONAL_ID}\nBank account: {IBAN}\nEmployee ID: {IDENTIFIER}\n"
        "Start date: {date}."
    ),
    "en_insurance": (
        "Claim number {IDENTIFIER}\nThe policyholder, {PERSON}, of {ADDRESS}, reports water "
        "damage on {date}. Contact: {PHONE}, {EMAIL}."
    ),
}

TEMPLATES = {"fr": FR_TEMPLATES, "en": EN_TEMPLATES}
_VALIDATION = {"fr_hr", "fr_insurance", "en_hr", "en_insurance"}
_SLOT = re.compile(r"\{([A-Za-z_]+)\}")


def templates_for(split: str) -> dict[str, tuple[str, str]]:
    """Templates of a split, as {name: (language, text)}."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    return {
        name: (language, text)
        for language, templates in TEMPLATES.items()
        for name, text in templates.items()
        if (name in _VALIDATION) == (split == "validation")
    }


# --- generation -------------------------------------------------------------------------------


def generate(n: int, split: str = "train", seed: int = 0) -> list[Example]:
    """`n` documents from the templates of `split` that pass the quality gates, reproducible from
    `seed`."""
    return generate_with_report(n, split, seed)[0]


def generate_with_report(
    n: int, split: str = "train", seed: int = 0
) -> tuple[list[Example], Counter]:
    """Like `generate`, also returning the rejected candidates counted by reason."""
    rng = random.Random(f"{seed}-{split}")
    templates = sorted(templates_for(split).items())
    examples: list[Example] = []
    rejected: Counter = Counter()
    attempts = 0
    while len(examples) < n:
        attempts += 1
        if attempts > 20 * n + 100:  # a template that always fails a gate must not hang the build
            raise RuntimeError(f"too many rejected documents: {dict(rejected)}")
        name, (language, template) = rng.choice(templates)
        locale = LOCALES["fr"] if language == "fr" else LOCALES[rng.choice(["en_us", "en_gb"])]
        example = _fill(name, language, template, IdentityFactory(locale, rng))
        problems = quality.check(example.text, example.spans, example.negatives)
        if problems:
            rejected.update(quality.summarise([problems]))
            continue
        examples.append(example)
    return examples, rejected


def _fill(name: str, language: str, template: str, factory: IdentityFactory) -> Example:
    identity = factory.identity()
    fake = factory.fake
    company = fake.company()
    first_name = factory.name_as(identity)
    later_names = [first_name, identity.person.last, factory.name_as(identity, "initial")]
    names_used = 0

    def person() -> str:
        # The first mention follows any style; later mentions repeat it or shorten it ("Dupont",
        # "J. Dupont"), as a letter signed after an introduction does.
        nonlocal names_used
        names_used += 1
        return first_name if names_used == 1 else factory.rng.choice(later_names)

    values = {
        "PERSON": person,
        "ADDRESS": lambda: factory.address_as(identity, multiline=False),
        "EMAIL": lambda: identity.email,
        "PHONE": lambda: factory.phone_as(identity),
        "IBAN": lambda: factory.iban_as(identity),
        "NATIONAL_ID": lambda: factory.national_id_as(identity),
        "BIRTH_DATE": lambda: factory.date_as(identity.birth_date),
        "IDENTIFIER": lambda: identity.identifier,
        "NATIONAL_ID_NAME": lambda: _NATIONAL_ID_NAMES[identity.national_id_kind],
        "date": lambda: factory.date_as(fake.date_between(date(2023, 1, 1), date(2026, 12, 31))),
        "amount": lambda: _amount(factory),
        "org": lambda: company,
        "org_email": lambda: (
            factory.rng.choice(["contact", "accueil", "frontdesk", "info"])
            + "@"
            + re.sub(r"[^a-z]", "", company.lower())[:12]
            + ".example"
        ),
        "city": fake.city,
    }
    text, spans, negatives = [], [], []
    length = cursor = 0
    for match in _SLOT.finditer(template):
        literal = template[cursor : match.start()]
        text.append(literal)
        length += len(literal)
        slot = match.group(1)
        value = values[slot]()
        if slot in EntityType.__members__:
            spans.append(Span(length, length + len(value), slot))
        elif slot in _NEGATIVE_SLOTS:
            negatives.append(Span(length, length + len(value), _NEGATIVE_SLOTS[slot]))
        text.append(value)
        length += len(value)
        cursor = match.end()
    text.append(template[cursor:])
    return Example("".join(text), spans, language, factory.locale, name, negatives)


# Distractor slots whose value looks like personal data of the given type but is not.
_NEGATIVE_SLOTS = {"org_email": "EMAIL"}

_NATIONAL_ID_NAMES = {
    "FR_NIR": "N° de sécurité sociale",
    "UK_NINO": "National Insurance number",
    "US_SSN": "SSN",
}


def _amount(factory: IdentityFactory) -> str:
    value = factory.rng.randrange(20, 2000)
    symbol = {"fr_FR": "{} €", "en_GB": "£{}"}.get(factory.locale, "${}")
    return symbol.format(value)


def write_jsonl(examples: list[Example], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for example in examples:
            out.write(json.dumps(asdict(example), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=SPLITS, default="train")
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write_jsonl(generate(args.n, args.split, args.seed), args.out)


if __name__ == "__main__":
    main()
