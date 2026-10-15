"""Fake identities with varied surface forms, for the synthetic dataset (docs/DATASET.md §3).

An identity is drawn once per document; the templates then pick how each value is written
("Jean Dupont", "DUPONT Jean", "J. Dupont"; "06 12 34 56 78" or "+33 6 12 34 56 78"). Every value
is fake: Faker for names and addresses, format generators with valid checksums for the rest.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass
from datetime import date

import phonenumbers
from faker import Faker

# Names are drawn from many origins, so the detector is not trained only on common French and
# English names (docs/DATASET.md §10). Faker locales give Latin-script names; the lists below add
# frequent names from origins Faker does not cover in Latin script.
NAME_LOCALES = ("fr_FR", "en_GB", "en_US", "es_ES", "pt_PT", "it_IT", "de_DE", "pl_PL", "nl_NL",
                "ro_RO", "tr_TR")  # fmt: skip
OTHER_ORIGINS = {
    "maghreb": (["Mohamed", "Fatima", "Yassine", "Amina", "Karim", "Nadia", "Mehdi", "Leila"],
                ["Benali", "Haddad", "El Amrani", "Bouzid", "Cherif", "Mansouri", "Belkacem"]),
    "west_africa": (["Mamadou", "Aïssatou", "Ousmane", "Fatoumata", "Ibrahima", "Awa", "Seydou"],
                    ["Diallo", "Traoré", "Ndiaye", "Koné", "Diop", "Camara", "Ouédraogo"]),
    "vietnam": (["Thi Lan", "Van Minh", "Thanh", "Huong", "Quang", "Mai"],
                ["Nguyen", "Tran", "Le", "Pham", "Hoang", "Vu"]),
    "china": (["Wei", "Jing", "Xiaoming", "Li Na", "Hao", "Mei"],
              ["Wang", "Li", "Zhang", "Liu", "Chen", "Zhao"]),
    "india": (["Priya", "Rahul", "Ananya", "Arjun", "Deepika", "Vikram"],
              ["Sharma", "Patel", "Singh", "Iyer", "Reddy", "Gupta"]),
}  # fmt: skip
IBAN_LOCALES = {"FR": "fr_FR", "GB": "en_GB", "DE": "de_DE", "ES": "es_ES", "IT": "it_IT",
                "BE": "nl_BE", "NL": "nl_NL", "PT": "pt_PT"}  # fmt: skip
FR_MONTHS = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre"
EN_MONTHS = "January February March April May June July August September October November December"


@dataclass(frozen=True)
class Person:
    first: str
    last: str
    origin: str  # Faker locale or one of OTHER_ORIGINS, to report recall by origin

    def forms(self) -> dict[str, str]:
        """Ways the same person is written in documents."""
        return {
            "full": f"{self.first} {self.last}",
            "admin": f"{self.last.upper()} {self.first}",  # French administrative style
            "upper_last": f"{self.first} {self.last.upper()}",
            "last": self.last,
            "initial": f"{self.first[0]}. {self.last}",
            "comma": f"{self.last}, {self.first}",
            "upper": f"{self.first} {self.last}".upper(),
        }


@dataclass(frozen=True)
class Identity:
    """All the personal values of one fake person, in a canonical form."""

    locale: str
    person: Person
    address_lines: tuple[str, ...]
    email: str
    phone: str  # E.164
    iban: str  # compact
    national_id: str  # compact
    national_id_kind: str  # FR_NIR, US_SSN, UK_NINO
    birth_date: date
    identifier: str


class IdentityFactory:
    """Draws identities and renders their values in varied surface forms, reproducibly."""

    def __init__(self, locale: str, rng: random.Random):
        self.locale = locale
        self.rng = rng
        self.fake = self._faker(locale)

    def _faker(self, locale: str) -> Faker:
        fake = Faker(locale)
        fake.seed_instance(self.rng.randrange(2**32))
        return fake

    def _digits(self, count: int) -> str:
        return "".join(str(self.rng.randrange(10)) for _ in range(count))

    # --- drawing ------------------------------------------------------------------------------

    def identity(self) -> Identity:
        person = self.person()
        national_id, kind = self.national_id()
        return Identity(
            locale=self.locale,
            person=person,
            address_lines=self.address_lines(),
            email=self.email_for(person),
            phone=self.phone(),
            iban=self.iban(),
            national_id=national_id,
            national_id_kind=kind,
            birth_date=self.fake.date_between(date(1935, 1, 1), date(2007, 12, 31)),
            identifier=self.identifier(),
        )

    def person(self) -> Person:
        if self.rng.random() < 0.35:
            origin = self.rng.choice(sorted(OTHER_ORIGINS))
            firsts, lasts = OTHER_ORIGINS[origin]
            first, last = self.rng.choice(firsts), self.rng.choice(lasts)
        else:
            origin = self.locale if self.rng.random() < 0.6 else self.rng.choice(NAME_LOCALES)
            fake = self._faker(origin)
            first, last = fake.first_name(), fake.last_name()
        if self.rng.random() < 0.1:  # compound first name
            first = f"{first}-{self.rng.choice(['Marie', 'Pierre', 'Louise', 'Anne', 'Paul'])}"
        if self.rng.random() < 0.08:  # double surname
            last = f"{last}-{self._faker(self.locale).last_name()}"
        return Person(first, last, origin)

    def address_lines(self) -> tuple[str, ...]:
        fake, r = self.fake, self.rng.random()
        if self.locale == "fr_FR":
            street = fake.street_address()
            if r < 0.15:
                number, _, rest = street.partition(" ")
                street = f"{number} {self.rng.choice(['bis', 'ter'])} {rest}"
            lines = [street]
            if r > 0.85:
                lines.append(f"Lieu-dit {fake.last_name()}")
            town = fake.city()
            city = f"{fake.postcode()} {town.upper() if self.rng.random() < 0.3 else town}"
            if self.rng.random() < 0.05:
                city += " CEDEX"
            return (*lines, city)
        if self.locale == "en_GB":
            lines = [fake.street_address().replace("\n", ", ")]
            if r < 0.3 and not lines[0].startswith(("Flat", "Studio")):
                lines.insert(0, f"Flat {self.rng.randrange(1, 40)}")
            return (*lines, fake.city(), fake.postcode())
        lines = [fake.street_address().replace("\n", ", ")]
        return (*lines, f"{fake.city()}, {fake.state_abbr()} {fake.zipcode()}")

    def email_for(self, person: Person) -> str:
        """Derived from the person's name most of the time, as real addresses are."""

        def clean(text: str) -> str:  # e-mail local parts are ASCII in practice
            ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
            return "".join(c for c in ascii_text.lower() if c.isalnum())

        first, last = clean(person.first), clean(person.last)
        locals_ = [f"{first}.{last}", f"{first[0]}{last}", f"{last}{first[:3]}",
                   f"{first}{self.rng.randrange(10, 99)}", self.fake.user_name()]  # fmt: skip
        local = self.rng.choice(locals_)
        domain = (
            self.fake.free_email_domain() if self.rng.random() < 0.7 else self.fake.domain_name()
        )
        return f"{local}@{domain}"

    def phone(self) -> str:
        """E.164 number in an allocated range: random digits are often unallocated."""
        region = {"fr_FR": "FR", "en_GB": "GB"}.get(self.locale, "US")
        while True:
            if region == "FR":
                raw = "+33" + self.rng.choice("1234567") + self._digits(8)
            elif region == "GB":
                raw = "+44" + self.rng.choice(["7", "20", "121", "161"]) + self._digits(8)
            else:
                raw = (
                    "+1"
                    + str(self.rng.randrange(2, 10))
                    + self._digits(2)
                    + str(self.rng.randrange(2, 10))
                    + self._digits(6)
                )
            try:
                number = phonenumbers.parse(raw, None)
            except phonenumbers.NumberParseException:
                continue
            if phonenumbers.is_valid_number(number):
                return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)

    def iban(self) -> str:
        if self.locale == "fr_FR":
            country = "FR" if self.rng.random() < 0.8 else self.rng.choice(sorted(IBAN_LOCALES))
        elif self.locale == "en_GB":
            country = "GB" if self.rng.random() < 0.8 else self.rng.choice(sorted(IBAN_LOCALES))
        else:
            country = self.rng.choice(sorted(IBAN_LOCALES))
        return self._faker(IBAN_LOCALES[country]).iban()

    def national_id(self) -> tuple[str, str]:
        if self.locale == "fr_FR":
            nir = self.fake.ssn()
            if self.rng.random() < 0.05:  # born in Corsica: department 2A or 2B, key recomputed
                body = nir[:5] + self.rng.choice(["2A", "2B"]) + nir[7:13]
                key = 97 - int(body.replace("2A", "19").replace("2B", "18")) % 97
                nir = f"{body}{key:02d}"
            return nir, "FR_NIR"
        if self.locale == "en_GB":
            prefix = self.rng.choice(["AB", "CE", "JG", "KL", "PR", "SW", "TY", "WX", "HM", "NP"])
            return f"{prefix}{self._digits(6)}{self.rng.choice('ABCD')}", "UK_NINO"
        return self.fake.ssn().replace("-", ""), "US_SSN"

    def identifier(self) -> str:
        d = self._digits
        forms = [f"{self.rng.randrange(2015, 2027)}/{d(5)}", f"AB-{d(6)}", f"C{d(7)}",
                 f"{d(3)}-{d(4)}-{d(2)}", f"DOS{d(6)}", d(10), f"REF-{d(4)}-{d(3)}"]  # fmt: skip
        return self.rng.choice(forms)

    # --- surface forms ------------------------------------------------------------------------

    def name_as(self, identity: Identity, style: str | None = None) -> str:
        forms = identity.person.forms()
        weights = {
            "full": 45,
            "admin": 10,
            "upper_last": 8,
            "last": 12,
            "initial": 10,
            "comma": 5,
            "upper": 10,
        }
        style = style or self.rng.choices(list(weights), weights=list(weights.values()))[0]
        return forms[style]

    def address_as(self, identity: Identity, multiline: bool | None = None) -> str:
        multiline = self.rng.random() < 0.4 if multiline is None else multiline
        return ("\n" if multiline else ", ").join(identity.address_lines)

    def phone_as(self, identity: Identity) -> str:
        number = phonenumbers.parse(identity.phone, None)
        style = self.rng.random()
        if style < 0.45:
            text = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
        elif style < 0.75:
            text = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        elif style < 0.9 and self.locale == "fr_FR":
            text = phonenumbers.format_number(
                number, phonenumbers.PhoneNumberFormat.NATIONAL
            ).replace(" ", ".")
        else:
            text = phonenumbers.format_number(
                number, phonenumbers.PhoneNumberFormat.NATIONAL
            ).replace(" ", "")
        return text

    def iban_as(self, identity: Identity) -> str:
        r = self.rng.random()
        grouped = " ".join(identity.iban[i : i + 4] for i in range(0, len(identity.iban), 4))
        return grouped if r < 0.6 else identity.iban if r < 0.9 else grouped.lower()

    def national_id_as(self, identity: Identity) -> str:
        value = identity.national_id
        if self.rng.random() < 0.5:
            return value
        if identity.national_id_kind == "FR_NIR":
            return " ".join(
                (
                    value[0],
                    value[1:3],
                    value[3:5],
                    value[5:7],
                    value[7:10],
                    value[10:13],
                    value[13:],
                )
            )
        if identity.national_id_kind == "UK_NINO":
            return " ".join((value[:2], value[2:4], value[4:6], value[6:8], value[8]))
        return f"{value[:3]}-{value[3:5]}-{value[5:]}"

    def date_as(self, day: date) -> str:
        r = self.rng.random()
        if self.locale == "fr_FR":
            if r < 0.6:
                return day.strftime("%d/%m/%Y")
            if r < 0.8:
                return f"{day.day} {FR_MONTHS.split()[day.month - 1]} {day.year}"
            return day.strftime("%d.%m.%Y")
        month = EN_MONTHS.split()[day.month - 1]
        if self.locale == "en_GB":
            return day.strftime("%d/%m/%Y") if r < 0.5 else f"{day.day} {month} {day.year}"
        return day.strftime("%m/%d/%Y") if r < 0.5 else f"{month} {day.day}, {day.year}"
