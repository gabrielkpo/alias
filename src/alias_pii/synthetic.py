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
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import phonenumbers
from faker import Faker

from alias_pii.entities import EntityType

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
        "De : {EMAIL}\nÀ : accueil@{org_domain}\nObjet : rendez-vous\n\nBonjour, je suis "
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
        "From: {EMAIL}\nTo: frontdesk@{org_domain}\nSubject: appointment\n\nHi, this is {PERSON}. "
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

EN_MONTHS = "January February March April May June July August September October November December"
FR_MONTHS = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre"


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


# --- values -----------------------------------------------------------------------------------


class _Values:
    """Personal and distractor values for one locale, with varied surface forms."""

    def __init__(self, locale: str, rng: random.Random):
        self.locale = locale
        self.rng = rng
        self.fake = Faker(locale)
        self.fake.seed_instance(rng.randrange(2**32))

    def digits(self, count: int) -> str:
        return "".join(str(self.rng.randrange(10)) for _ in range(count))

    def person(self) -> str:
        name = self.fake.name()
        return name.upper() if self.rng.random() < 0.1 else name

    def address(self) -> str:
        return self.fake.address().replace("\n", ", ")

    def email(self) -> str:
        return self.fake.email()

    def phone(self) -> str:
        """A number in an allocated range, as a real document would contain: random digits are
        often unallocated, and a detector would rightly ignore them."""
        region = {"fr_FR": "FR", "en_GB": "GB"}.get(self.locale, "US")
        while True:
            number = self._phone_candidate()
            if phonenumbers.is_valid_number(phonenumbers.parse(number, region)):
                return number

    def _phone_candidate(self) -> str:
        r, d = self.rng.random(), self.digits
        if self.locale == "fr_FR":
            body = [self.rng.choice("1234567"), *(d(2) for _ in range(4))]
            if r < 0.6:
                return "0" + body[0] + " " + " ".join(body[1:])
            if r < 0.8:
                return "+33 " + body[0] + " " + " ".join(body[1:])
            return "0" + body[0] + "." + ".".join(body[1:])
        if self.locale == "en_GB":
            return f"07{d(3)} {d(6)}" if r < 0.5 else f"+44 20 {d(4)} {d(4)}"
        area = f"{self.rng.randrange(2, 10)}{d(2)}"
        exchange = f"{self.rng.randrange(2, 10)}{d(2)}"
        return f"({area}) {exchange}-{d(4)}" if r < 0.5 else f"{area}-{exchange}-{d(4)}"

    def iban(self) -> str:
        country = {"fr_FR": "FR", "en_GB": "GB"}.get(self.locale, self.rng.choice(["GB", "FR"]))
        maker = Faker({"FR": "fr_FR", "GB": "en_GB"}[country])
        maker.seed_instance(self.rng.randrange(2**32))
        compact = maker.iban()
        if self.rng.random() < 0.6:  # usually printed in groups of four
            return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))
        return compact

    def national_id(self) -> tuple[str, str]:
        """(value, name of the number in the document)."""
        if self.locale == "fr_FR":
            nir = self.fake.ssn()
            if self.rng.random() < 0.5:
                parts = (nir[0], nir[1:3], nir[3:5], nir[5:7], nir[7:10], nir[10:13], nir[13:])
                nir = " ".join(parts)
            return nir, "N° de sécurité sociale"
        if self.locale == "en_GB":
            prefix = self.rng.choice(["AB", "CE", "JG", "KL", "PR", "SW", "TY", "WX"])
            value = f"{prefix} {self.digits(2)} {self.digits(2)} {self.digits(2)} "
            return value + self.rng.choice("ABCD"), "National Insurance number"
        return self.fake.ssn(), "SSN"

    def identifier(self) -> str:
        d = self.digits
        forms = [f"{self.rng.randrange(2018, 2027)}/{d(5)}", f"AB-{d(6)}", f"C{d(7)}"]
        return self.rng.choice(forms)

    def birth_date(self) -> str:
        # Fixed bounds rather than "age 18 to 90": the output must not depend on today's date.
        return self._format_date(self.fake.date_between(date(1935, 1, 1), date(2007, 12, 31)))

    def other_date(self) -> str:
        return self._format_date(self.fake.date_between(date(2023, 1, 1), date(2026, 12, 31)))

    def _format_date(self, day: date) -> str:
        r = self.rng.random()
        if self.locale == "fr_FR":
            if r < 0.6:
                return day.strftime("%d/%m/%Y")
            return f"{day.day} {FR_MONTHS.split()[day.month - 1]} {day.year}"
        if r < 0.5:
            return day.strftime("%d/%m/%Y" if self.locale == "en_GB" else "%m/%d/%Y")
        month = EN_MONTHS.split()[day.month - 1]
        return (
            f"{day.day} {month} {day.year}"
            if self.locale == "en_GB"
            else f"{month} {day.day}, {day.year}"
        )

    def amount(self) -> str:
        value = self.rng.randrange(20, 2000)
        symbol = {"fr_FR": "{} €", "en_GB": "£{}"}.get(self.locale, "${}")
        return symbol.format(value)


# --- generation -------------------------------------------------------------------------------


def generate(n: int, split: str = "train", seed: int = 0) -> list[Example]:
    """`n` documents from the templates of `split`, reproducible from `seed`."""
    rng = random.Random(f"{seed}-{split}")
    templates = sorted(templates_for(split).items())
    examples = []
    for _ in range(n):
        name, (language, template) = rng.choice(templates)
        locale = LOCALES["fr"] if language == "fr" else LOCALES[rng.choice(["en_us", "en_gb"])]
        examples.append(_fill(name, language, template, _Values(locale, rng)))
    return examples


def _fill(name: str, language: str, template: str, values: _Values) -> Example:
    # One person, one national ID per document: repeated slots repeat the same value, as in a
    # real letter signed by the person who wrote it.
    person = values.person()
    national_id, national_id_name = values.national_id()
    company = values.fake.company()
    fixed = {
        "PERSON": person,
        "NATIONAL_ID": national_id,
        "NATIONAL_ID_NAME": national_id_name,
        "org": company,
        "org_domain": re.sub(r"[^a-z]", "", company.lower())[:12] + ".example",
        "city": values.fake.city(),
    }
    makers = {
        "ADDRESS": values.address,
        "EMAIL": values.email,
        "PHONE": values.phone,
        "IBAN": values.iban,
        "IDENTIFIER": values.identifier,
        "BIRTH_DATE": values.birth_date,
        "date": values.other_date,
        "amount": values.amount,
    }
    text, spans, cursor = [], [], 0
    for match in _SLOT.finditer(template):
        text.append(template[cursor : match.start()])
        slot = match.group(1)
        value = fixed[slot] if slot in fixed else makers[slot]()
        start = sum(len(part) for part in text)
        text.append(value)
        if slot in EntityType.__members__:
            spans.append(Span(start, start + len(value), slot))
        cursor = match.end()
    text.append(template[cursor:])
    return Example("".join(text), spans, language, values.locale, name)


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
