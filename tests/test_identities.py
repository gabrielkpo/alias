import random
from collections import Counter

import pytest

pytest.importorskip("faker")

from alias_pii.identities import OTHER_ORIGINS, IdentityFactory  # noqa: E402
from alias_pii.quality import _realistic  # noqa: E402
from alias_pii.validators import iban_is_valid, nir_is_valid  # noqa: E402


@pytest.fixture(scope="module", params=["fr_FR", "en_GB", "en_US"])
def drawn(request):
    factory = IdentityFactory(request.param, random.Random(5))
    return factory, [factory.identity() for _ in range(300)]


def test_canonical_values_are_valid(drawn):
    _, identities = drawn
    for identity in identities:
        assert iban_is_valid(identity.iban)
        if identity.national_id_kind == "FR_NIR":
            assert nir_is_valid(identity.national_id)
        assert identity.email.isascii() and "@" in identity.email


def test_every_surface_form_is_a_real_world_format(drawn):
    factory, identities = drawn
    for identity in identities:
        assert _realistic("IBAN", factory.iban_as(identity))
        assert _realistic("NATIONAL_ID", factory.national_id_as(identity))
        assert _realistic("PHONE", factory.phone_as(identity))
        assert _realistic("EMAIL", identity.email)


def test_names_come_from_many_origins(drawn):
    _, identities = drawn
    origins = Counter(identity.person.origin for identity in identities)
    assert len(origins) >= 8
    assert sum(origins[o] for o in OTHER_ORIGINS) > 0.2 * len(identities)


def test_corsican_nir_keys_are_valid():
    factory = IdentityFactory("fr_FR", random.Random(0))
    corsican = [
        i.national_id
        for i in (factory.identity() for _ in range(2000))
        if "2A" in i.national_id[5:7] or "2B" in i.national_id[5:7]
    ]
    assert corsican and all(nir_is_valid(nir) for nir in corsican)
