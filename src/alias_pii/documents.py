"""Grid-based document generator (dataset v0.2, docs/DATASET.md §3 to §7).

A document is assembled, not filled in: a document type (with its domain) chooses which personal
fields it carries, a layout (prose, key-value form, table, e-mail thread, chat) arranges them,
phrase banks in French and English word them, and distractors that look personal but are not are
mixed in. Spans are recorded while the text is built, so labels are exact by construction.

Splits are leak-free: phrase variants are divided between train and evaluation by a stable hash,
every document draws a fresh identity, and one document type (meeting minutes) is reserved for the
test split.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from alias_pii.identities import Identity, IdentityFactory

LABELS = ("PERSON", "ADDRESS", "EMAIL", "PHONE", "IBAN", "NATIONAL_ID", "BIRTH_DATE", "IDENTIFIER")
SPLITS = ("train", "validation", "test")
TEST_ONLY_TYPES = {"minutes"}


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str


@dataclass
class Document:
    text: str
    spans: list[Span]
    language: str  # "fr", "en" or "mixed"
    locale: str
    doc_type: str
    domain: str
    layout: str
    split: str
    source: str = "grid-v0.2"
    negatives: list[Span] = field(default_factory=list)
    person_origin: str = ""


# --- document types -------------------------------------------------------------------------
# fields: always present; optional: drawn by the balancer. Layouts the type is written in.

DOC_TYPES = {
    "letter": dict(domains=["administration", "insurance", "real_estate", "legal"], layouts=["prose"],
                   fields=["PERSON", "ADDRESS"], optional=["EMAIL", "PHONE", "IDENTIFIER", "BIRTH_DATE", "NATIONAL_ID"]),
    "email": dict(domains=["health", "banking", "e_commerce", "telecom", "education"], layouts=["email"],
                  fields=["PERSON", "EMAIL"], optional=["PHONE", "IDENTIFIER", "ADDRESS", "IBAN"]),
    "form": dict(domains=["administration", "health", "education", "insurance"], layouts=["key_value"],
                 fields=["PERSON", "BIRTH_DATE"], optional=["ADDRESS", "EMAIL", "PHONE", "NATIONAL_ID", "IBAN", "IDENTIFIER"]),
    "invoice": dict(domains=["e_commerce", "telecom", "real_estate"], layouts=["key_value", "table"],
                    fields=["PERSON", "ADDRESS"], optional=["EMAIL", "PHONE", "IDENTIFIER", "IBAN"]),
    "contract": dict(domains=["real_estate", "hr", "telecom", "banking"], layouts=["prose"],
                     fields=["PERSON", "ADDRESS"], optional=["BIRTH_DATE", "IBAN", "IDENTIFIER", "NATIONAL_ID"]),
    "medical_report": dict(domains=["health"], layouts=["key_value", "prose"],
                           fields=["PERSON", "BIRTH_DATE"], optional=["NATIONAL_ID", "ADDRESS", "PHONE", "IDENTIFIER"]),
    "hr_file": dict(domains=["hr"], layouts=["key_value", "table"],
                    fields=["PERSON", "NATIONAL_ID"], optional=["BIRTH_DATE", "IBAN", "ADDRESS", "IDENTIFIER", "PHONE"]),
    "bank_statement": dict(domains=["banking"], layouts=["table", "key_value"],
                           fields=["PERSON", "IBAN"], optional=["ADDRESS", "IDENTIFIER"]),
    "insurance_claim": dict(domains=["insurance"], layouts=["prose", "email", "key_value"],
                            fields=["PERSON", "IDENTIFIER"], optional=["ADDRESS", "PHONE", "EMAIL", "IBAN", "BIRTH_DATE", "NATIONAL_ID"]),
    "cv": dict(domains=["hr", "education"], layouts=["key_value", "prose"],
               fields=["PERSON", "EMAIL"], optional=["PHONE", "ADDRESS", "BIRTH_DATE"]),
    "support_ticket": dict(domains=["telecom", "e_commerce", "banking"], layouts=["email", "key_value"],
                           fields=["PERSON", "IDENTIFIER"], optional=["EMAIL", "PHONE", "ADDRESS"]),
    "chat": dict(domains=["e_commerce", "telecom", "health"], layouts=["chat"],
                 fields=["PERSON"], optional=["PHONE", "EMAIL", "IDENTIFIER", "ADDRESS", "IBAN"]),
    "notes": dict(domains=["health", "legal", "hr", "administration"], layouts=["prose", "chat"],
                  fields=["PERSON"], optional=["PHONE", "BIRTH_DATE", "ADDRESS", "IDENTIFIER", "NATIONAL_ID"]),
    "minutes": dict(domains=["administration", "hr", "legal"], layouts=["prose"],
                    fields=["PERSON"], optional=["EMAIL", "PHONE", "IDENTIFIER", "BIRTH_DATE"]),
}  # fmt: skip

TITLES = {
    "fr": {"letter": "Courrier", "email": "", "form": "Formulaire de demande", "invoice": "Facture",
           "contract": "Contrat", "medical_report": "Compte rendu médical", "hr_file": "Fiche salarié",
           "bank_statement": "Relevé de compte", "insurance_claim": "Déclaration de sinistre",
           "cv": "Curriculum vitae", "support_ticket": "Ticket d'assistance", "chat": "",
           "notes": "Notes", "minutes": "Procès-verbal de réunion"},
    "en": {"letter": "Letter", "email": "", "form": "Application form", "invoice": "Invoice",
           "contract": "Agreement", "medical_report": "Medical report", "hr_file": "Employee record",
           "bank_statement": "Account statement", "insurance_claim": "Insurance claim",
           "cv": "Curriculum vitae", "support_ticket": "Support ticket", "chat": "",
           "notes": "Notes", "minutes": "Meeting minutes"},
}  # fmt: skip

# --- phrase banks -----------------------------------------------------------------------------
# Field names for forms and tables, and sentences for prose. {v} is the personal value.

FIELD_NAMES = {
    "fr": {
        "PERSON": ["Nom", "Nom et prénom", "Patient", "Assuré", "Titulaire", "Salarié", "Client", "Destinataire", "Demandeur", "Locataire"],
        "ADDRESS": ["Adresse", "Domicile", "Adresse postale", "Adresse de facturation", "Lieu de résidence"],
        "EMAIL": ["E-mail", "Courriel", "Adresse électronique", "Mail", "Adresse mail"],
        "PHONE": ["Téléphone", "Tél.", "Portable", "Tél. mobile", "N° de téléphone", "Contact"],
        "IBAN": ["IBAN", "Coordonnées bancaires", "Compte à débiter", "RIB (IBAN)", "Compte"],
        "NATIONAL_ID": ["N° de sécurité sociale", "NIR", "N° SS", "Numéro de sécu"],
        "BIRTH_DATE": ["Date de naissance", "Né(e) le", "Naissance", "Date de naiss."],
        "IDENTIFIER": ["N° de dossier", "Référence client", "N° de contrat", "Matricule", "N° adhérent", "N° de sinistre", "Réf.", "Identifiant"],
    },
    "en": {
        "PERSON": ["Name", "Full name", "Patient", "Policyholder", "Account holder", "Employee", "Customer", "Recipient", "Applicant", "Tenant"],
        "ADDRESS": ["Address", "Home address", "Mailing address", "Billing address", "Residence"],
        "EMAIL": ["Email", "E-mail", "Email address", "Contact email"],
        "PHONE": ["Phone", "Tel.", "Mobile", "Phone number", "Contact number"],
        "IBAN": ["IBAN", "Bank account", "Account (IBAN)", "Payment account"],
        "NATIONAL_ID": ["National ID", "ID number"],
        "BIRTH_DATE": ["Date of birth", "DOB", "Born", "Birth date"],
        "IDENTIFIER": ["File number", "Customer ID", "Contract number", "Policy number", "Employee ID", "Claim number", "Reference", "Account ID"],
    },
}  # fmt: skip
NATIONAL_ID_NAMES = {
    "US_SSN": ["SSN", "Social Security number", "SS#"],
    "UK_NINO": ["National Insurance number", "NI number", "NINO"],
}

SENTENCES = {
    "fr": {
        "PERSON": ["Ce dossier concerne {v}.", "{v} a contacté nos services la semaine dernière.", "Je soussigné(e) {v}, certifie l'exactitude des informations.",
                   "Merci de transmettre ce document à {v}.", "La demande a été déposée par {v}.", "{v} sera présent(e) au rendez-vous."],
        "ADDRESS": ["Le courrier doit être envoyé au {v}.", "Domicile actuel : {v}.", "Le logement situé {v} est concerné.",
                    "Merci de noter ma nouvelle adresse : {v}.", "La livraison est prévue au {v}."],
        "EMAIL": ["Vous pouvez écrire à {v}.", "Réponse attendue à l'adresse {v}.", "Les justificatifs ont été envoyés depuis {v}.",
                  "Pour toute question : {v}."],
        "PHONE": ["Joignable au {v} en journée.", "Merci de rappeler le {v}.", "En cas d'urgence, composer le {v}.",
                  "Le numéro communiqué est le {v}."],
        "IBAN": ["Le remboursement sera versé sur le compte {v}.", "Merci de prélever le compte {v} chaque mois.",
                 "Le virement a été émis depuis le compte {v}.", "Nouvelles coordonnées bancaires : {v}."],
        "NATIONAL_ID": ["Son numéro de sécurité sociale est le {v}.", "Le NIR {v} figure sur la carte Vitale.",
                        "Merci d'indiquer le numéro {v} sur la feuille de soins."],
        "BIRTH_DATE": ["La personne est née le {v}.", "Date de naissance déclarée : {v}.", "Né(e) le {v}, l'assuré(e) a fourni ses justificatifs."],
        "IDENTIFIER": ["Merci de rappeler la référence {v} dans toute correspondance.", "Votre dossier {v} est en cours de traitement.",
                       "La demande enregistrée sous le numéro {v} est complète.", "Contrat {v} : renouvellement automatique."],
    },
    "en": {
        "PERSON": ["This file concerns {v}.", "{v} contacted our team last week.", "I, {v}, confirm that the information above is correct.",
                   "Please forward this document to {v}.", "The request was submitted by {v}.", "{v} will attend the appointment."],
        "ADDRESS": ["Please send the letter to {v}.", "Current address: {v}.", "The property at {v} is concerned.",
                    "Please note my new address: {v}.", "Delivery is scheduled to {v}."],
        "EMAIL": ["You can write to {v}.", "Please reply to {v}.", "The documents were sent from {v}.", "For any question: {v}."],
        "PHONE": ["Reachable on {v} during the day.", "Please call back on {v}.", "In an emergency, dial {v}.", "The number given is {v}."],
        "IBAN": ["The refund will be paid into account {v}.", "Please debit account {v} every month.",
                 "The transfer was made from account {v}.", "New bank details: {v}."],
        "NATIONAL_ID": ["Their national identification number is {v}.", "The number {v} appears on the card.",
                        "Please quote {v} on the form."],
        "BIRTH_DATE": ["The person was born on {v}.", "Declared date of birth: {v}.", "Born on {v}, the applicant provided proof of identity."],
        "IDENTIFIER": ["Please quote reference {v} in any correspondence.", "Your file {v} is being processed.",
                       "The request registered under number {v} is complete.", "Contract {v}: automatic renewal."],
    },
}  # fmt: skip

# Distractors: look personal, are not. Declared kinds are checked by the quality gates.
NEGATIVE_SENTENCES = {
    "fr": ["La réunion est prévue le {date}.", "Montant total : {amount}.", "Facture n° {invoice}.", "Commande {order} expédiée.",
           "Pour joindre le standard de {org} : {org_phone}.", "Service client : {org_email}.", "Siège social de {org} : {org_address}.",
           "Dossier transmis à la CPAM de {city}.", "Référence produit {product}.", "Échéance au {date}."],
    "en": ["The meeting is scheduled for {date}.", "Total amount: {amount}.", "Invoice no. {invoice}.", "Order {order} shipped.",
           "To reach the {org} switchboard: {org_phone}.", "Customer service: {org_email}.", "{org} head office: {org_address}.",
           "File sent to the {city} council.", "Product reference {product}.", "Due date: {date}."],
}  # fmt: skip
NEGATIVE_KINDS = {"org_phone": "PHONE", "org_email": "EMAIL", "org_address": "ADDRESS"}

GREETINGS = {"fr": ["Bonjour,", "Madame, Monsieur,", "Bonjour à tous,", "Cher client,"],
             "en": ["Hello,", "Dear Sir or Madam,", "Hi all,", "Dear customer,"]}  # fmt: skip
CLOSINGS = {"fr": ["Cordialement,", "Bien à vous,", "Veuillez agréer mes salutations distinguées.", "Merci d'avance,"],
            "en": ["Kind regards,", "Best,", "Yours faithfully,", "Thanks in advance,"]}  # fmt: skip


def _split_of(variant: str) -> str:
    """Stable assignment of a phrase variant: 80 % train, 10 % validation, 10 % test."""
    bucket = int(hashlib.sha256(variant.encode()).hexdigest(), 16) % 10
    return "train" if bucket < 8 else "validation" if bucket == 8 else "test"


def _bank(items: list[str], split: str) -> list[str]:
    chosen = [item for item in items if _split_of(item) == split]
    if chosen:
        return chosen
    # A small bank may have no variant for a split: fall back to the whole bank rather than fail.
    return items


# --- building ---------------------------------------------------------------------------------


class _Builder:
    """Appends text and records spans as it goes, so offsets are exact."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.length = 0
        self.spans: list[Span] = []
        self.negatives: list[Span] = []

    def text(self, literal: str) -> None:
        self.parts.append(literal)
        self.length += len(literal)

    def value(self, value: str, label: str | None = None, negative: str | None = None) -> None:
        if label:
            self.spans.append(Span(self.length, self.length + len(value), label))
        elif negative:
            self.negatives.append(Span(self.length, self.length + len(value), negative))
        self.text(value)

    def sentence(self, pattern: str, values: dict[str, tuple[str, str | None, str | None]]) -> None:
        """Write a pattern whose {name} slots are filled from `values` (value, label, negative)."""
        rest = pattern
        while "{" in rest:
            before, _, after = rest.partition("{")
            name, _, rest = after.partition("}")
            self.text(before)
            value, label, negative = values[name]
            self.value(value, label, negative)
        self.text(rest)

    def build(self) -> str:
        return "".join(self.parts)


class Balancer:
    """Chooses optional fields so each label's share of all spans moves toward an equal share."""

    def __init__(self) -> None:
        self.counts: Counter = Counter()

    def choose(
        self, optional: list[str], k: int, rng: random.Random, balance: bool = True
    ) -> list[str]:
        total = sum(self.counts.values()) + 1
        target = 1 / len(LABELS)
        if balance:
            weights = [max(target - self.counts[label] / total, 0) + 0.02 for label in optional]
        else:  # natural proportions: every optional field equally likely
            weights = [1.0] * len(optional)
        chosen: list[str] = []
        pool, pool_weights = list(optional), list(weights)
        for _ in range(min(k, len(pool))):
            index = rng.choices(range(len(pool)), weights=pool_weights)[0]
            chosen.append(pool.pop(index))
            pool_weights.pop(index)
        return chosen

    def record(self, spans: list[Span]) -> None:
        self.counts.update(span.label for span in spans)


class GridGenerator:
    def __init__(self, split: str, seed: int = 0, balance: bool | None = None) -> None:
        if split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}")
        self.split = split
        # Training is balanced; validation and test keep natural proportions (docs/DATASET.md §6).
        self.balance = split == "train" if balance is None else balance
        self.rng = random.Random(f"grid-{seed}-{split}")
        self.balancer = Balancer()
        types = list(DOC_TYPES)
        self.doc_types = (
            types if split == "test" else [t for t in types if t not in TEST_ONLY_TYPES]
        )

    def document(self) -> Document:
        rng = self.rng
        doc_type = rng.choice(self.doc_types)
        spec = DOC_TYPES[doc_type]
        language = "mixed" if rng.random() < 0.05 else rng.choice(["fr", "en"])
        locale = "fr_FR" if language in ("fr", "mixed") else rng.choice(["en_US", "en_GB"])
        factory = IdentityFactory(locale, rng)
        identity = factory.identity()
        layout = "email" if language == "mixed" else rng.choice(spec["layouts"])
        k = rng.randint(2, 4) if self.balance else rng.randint(1, 3)
        fields = list(spec["fields"]) + self.balancer.choose(spec["optional"], k, rng, self.balance)
        rng.shuffle(fields)
        fields.remove("PERSON")
        fields.insert(0, "PERSON")  # the person is introduced first
        values = self._values(factory, identity, fields)
        builder = _Builder()
        text_language = "fr" if language == "mixed" else language
        render = getattr(self, f"_{layout}")
        render(builder, text_language, doc_type, fields, values, factory, identity)
        if language == "mixed":
            self._quoted_reply(builder, values, factory)
        text = _noise(builder, rng)
        document = Document(
            text=text,
            spans=builder.spans,
            language=language,
            locale=locale,
            doc_type=doc_type,
            domain=rng.choice(spec["domains"]),
            layout=layout,
            split=self.split,
            negatives=builder.negatives,
            person_origin=identity.person.origin,
        )
        return document

    # --- values -----------------------------------------------------------------------------

    def _values(self, factory: IdentityFactory, identity: Identity, fields: list[str]) -> dict:
        rng, fake = factory.rng, factory.fake
        company = fake.company()
        domain = "".join(c for c in company.lower() if c.isalpha())[:12] or "corp"
        org_number = factory.phone()  # a switchboard: same format as a personal number
        values = {
            "PERSON": (factory.name_as(identity), "PERSON", None),
            "ADDRESS": (factory.address_as(identity), "ADDRESS", None),
            "EMAIL": (identity.email, "EMAIL", None),
            "PHONE": (factory.phone_as(identity), "PHONE", None),
            "IBAN": (factory.iban_as(identity), "IBAN", None),
            "NATIONAL_ID": (factory.national_id_as(identity), "NATIONAL_ID", None),
            "BIRTH_DATE": (factory.date_as(identity.birth_date), "BIRTH_DATE", None),
            "IDENTIFIER": (identity.identifier, "IDENTIFIER", None),
            "date": (
                factory.date_as(fake.date_between(date(2023, 1, 1), date(2026, 12, 31))),
                None,
                None,
            ),
            "amount": (
                f"{rng.randrange(10, 5000)},{rng.randrange(10, 99)} €"
                if factory.locale == "fr_FR"
                else f"{rng.randrange(10, 5000)}.{rng.randrange(10, 99)}",
                None,
                None,
            ),
            "invoice": (f"F-{rng.randrange(2023, 2027)}-{rng.randrange(1, 99999):05d}", None, None),
            "order": (f"#{rng.randrange(100000, 999999)}", None, None),
            "product": (
                f"{rng.choice('ABCDEFGH')}{rng.randrange(100, 999)}-{rng.choice('XYZ')}",
                None,
                None,
            ),
            "org": (company, None, None),
            "org_phone": (factory.phone_as(_with_phone(identity, org_number)), None, "PHONE"),
            "org_email": (
                f"{rng.choice(['contact', 'service', 'info', 'accueil', 'support'])}@{domain}.example",
                None,
                "EMAIL",
            ),
            "org_address": (", ".join(factory.address_lines()), None, "ADDRESS"),
            "city": (fake.city(), None, None),
        }
        later = [identity.person.last, factory.name_as(identity, "initial"), values["PERSON"][0]]
        values["PERSON_AGAIN"] = (rng.choice(later), "PERSON", None)
        return values

    def _negatives(self, language: str, n: int) -> list[str]:
        return [self.rng.choice(_bank(NEGATIVE_SENTENCES[language], self.split)) for _ in range(n)]

    def _field_name(self, language: str, label: str, identity: Identity) -> str:
        if label == "NATIONAL_ID" and identity.national_id_kind in NATIONAL_ID_NAMES:
            return self.rng.choice(NATIONAL_ID_NAMES[identity.national_id_kind])
        return self.rng.choice(_bank(FIELD_NAMES[language][label], self.split))

    # --- layouts ----------------------------------------------------------------------------

    def _title(self, b: _Builder, language: str, doc_type: str, values: dict) -> None:
        title = TITLES[language][doc_type]
        if title:
            b.text(f"{title.upper() if self.rng.random() < 0.3 else title} — ")
            b.value(values["org"][0])
            b.text("\n\n")

    def _prose(self, b, language, doc_type, fields, values, factory, identity) -> None:
        self._title(b, language, doc_type, values)
        if self.rng.random() < 0.5:
            b.sentence("{city}, ", {"city": values["city"]})
            b.sentence("{date}\n\n", {"date": values["date"]})
        b.text(self.rng.choice(GREETINGS[language]) + "\n\n")
        sentences = [
            (label, self.rng.choice(_bank(SENTENCES[language][label], self.split)))
            for label in fields
        ]
        sentences += [(None, s) for s in self._negatives(language, self.rng.randint(1, 3))]
        first, rest = sentences[0], sentences[1:]
        self.rng.shuffle(rest)
        for index, (label, pattern) in enumerate([first, *rest]):
            slot = {"v": values[label] if label else None, **values} if label else values
            b.sentence(pattern, slot)
            b.text(" " if index % 3 != 2 else "\n\n")
        b.text("\n\n" + self.rng.choice(CLOSINGS[language]) + "\n")
        self._signature(b, values)

    def _signature(self, b: _Builder, values: dict) -> None:
        if self.rng.random() < (0.4 if self.balance else 0.8):
            b.value(*values["PERSON_AGAIN"][:2])
        else:
            b.value(values["org"][0])

    def _key_value(self, b, language, doc_type, fields, values, factory, identity) -> None:
        self._title(b, language, doc_type, values)
        separator = self.rng.choice([" : ", ": ", " - ", "\t"])
        upper = self.rng.random() < 0.2
        for label in fields:
            name = self._field_name(language, label, identity)
            b.text((name.upper() if upper else name) + separator)
            value = values[label]
            if label == "ADDRESS" and self.rng.random() < 0.4:
                b.value(factory.address_as(identity, multiline=True), "ADDRESS")
            else:
                b.value(value[0], value[1])
            b.text("\n")
        b.text("\n")
        for pattern in self._negatives(language, self.rng.randint(1, 2)):
            b.sentence(pattern, values)
            b.text("\n")

    def _table(self, b, language, doc_type, fields, values, factory, identity) -> None:
        self._title(b, language, doc_type, values)
        names = [self._field_name(language, label, identity) for label in fields]
        delimiter = self.rng.choice([" | ", ";", ",", "\t"])
        if delimiter == ",":  # CSV: values with commas are quoted
            b.text(",".join(names) + "\n")
        else:
            b.text(delimiter.join(names) + "\n")
        for index, label in enumerate(fields):
            value = values[label][0]
            if delimiter == "," and "," in value:
                b.text('"')
                b.value(value, label)
                b.text('"')
            else:
                b.value(value, label)
            b.text(delimiter if index < len(fields) - 1 else "\n")
        b.text("\n")
        for pattern in self._negatives(language, self.rng.randint(1, 2)):
            b.sentence(pattern, values)
            b.text("\n")

    def _email(self, b, language, doc_type, fields, values, factory, identity) -> None:
        sender, subject = ("De", "Objet") if language == "fr" else ("From", "Subject")
        b.text(f"{sender} : " if language == "fr" else f"{sender}: ")
        b.value(values["EMAIL"][0], "EMAIL")
        b.text("\n" + ("À : " if language == "fr" else "To: "))
        b.value(*values["org_email"][:1], negative="EMAIL")
        b.text(f"\n{subject} : " if language == "fr" else f"\n{subject}: ")
        b.text(
            (TITLES[language][doc_type] or ("Demande" if language == "fr" else "Request")) + "\n\n"
        )
        b.text(self.rng.choice(GREETINGS[language]) + "\n\n")
        body = [label for label in fields if label != "EMAIL"]
        for label in body:
            b.sentence(
                self.rng.choice(_bank(SENTENCES[language][label], self.split)),
                {"v": values[label], **values},
            )
            b.text(" ")
        for pattern in self._negatives(language, self.rng.randint(0, 2)):
            b.sentence(pattern, values)
            b.text(" ")
        b.text("\n\n" + self.rng.choice(CLOSINGS[language]) + "\n")
        self._signature(b, values)

    def _chat(self, b, language, doc_type, fields, values, factory, identity) -> None:
        agent = "Conseiller" if language == "fr" else "Agent"
        lines_fr = {"PERSON": "c'est {v}", "PHONE": "mon num c {v}", "EMAIL": "mon mail {v}", "IDENTIFIER": "ma ref {v}",
                    "ADDRESS": "j'habite {v}", "IBAN": "iban {v}", "BIRTH_DATE": "né le {v}", "NATIONAL_ID": "secu {v}"}  # fmt: skip
        lines_en = {"PERSON": "it's {v}", "PHONE": "my number is {v}", "EMAIL": "email is {v}", "IDENTIFIER": "my ref is {v}",
                    "ADDRESS": "i live at {v}", "IBAN": "iban {v}", "BIRTH_DATE": "dob {v}", "NATIONAL_ID": "id {v}"}  # fmt: skip
        lines = lines_fr if language == "fr" else lines_en
        greeting = "bonjour" if language == "fr" else "hi"
        b.text(
            f"[{agent}] {greeting}, comment puis-je vous aider ?\n"
            if language == "fr"
            else f"[{agent}] {greeting}, how can I help?\n"
        )
        for label in fields:
            b.text("[Client] " if language == "fr" else "[Customer] ")
            b.sentence(lines[label], {"v": values[label]})
            b.text("\n")
        b.text(
            f"[{agent}] " + ("merci, je regarde" if language == "fr" else "thanks, checking") + "\n"
        )

    def _quoted_reply(self, b: _Builder, values: dict, factory: IdentityFactory) -> None:
        """Mixed-language thread: an English reply quoting the French message above."""
        b.text("\n\n> -----\n> Hello, thanks for your message. We will call you back on ")
        b.value(values["PHONE"][0], "PHONE")
        b.text(" as soon as possible.\n> Best regards,\n> ")
        b.value(*values["org"][:1])
        b.text("\n")


def _with_phone(identity: Identity, phone: str) -> Identity:
    from dataclasses import replace

    return replace(identity, phone=phone)


def _noise(b: _Builder, rng: random.Random) -> str:
    """Typos and extra line breaks in the literal text only: values are never altered."""
    if rng.random() < 0.15:
        labelled = sorted([*b.spans, *b.negatives], key=lambda s: s.start)
        text = b.build()
        for _ in range(rng.randint(1, 3)):
            position = rng.randrange(len(text) - 1)
            if not text[position].isalpha() or not text[position + 1].isalpha():
                continue
            if any(s.start <= position + 1 and position < s.end for s in labelled):
                continue
            text = text[:position] + text[position + 1] + text[position] + text[position + 2 :]
        return text
    return b.build()


def generate(n: int, split: str = "train", seed: int = 0) -> list[Document]:
    """`n` grid documents of a split (no quality gate here; see alias_pii.build_dataset)."""
    generator = GridGenerator(split, seed)
    documents = []
    for _ in range(n):
        document = generator.document()
        generator.balancer.record(document.spans)
        documents.append(document)
    return documents
