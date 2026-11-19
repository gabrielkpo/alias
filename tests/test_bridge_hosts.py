import pytest

pytest.importorskip("fastapi")

from alias_pii.bridge import LOCAL_HOSTS, host_name  # noqa: E402


@pytest.mark.parametrize(
    ("header", "host"),
    [
        ("127.0.0.1:8001", "127.0.0.1"),
        ("localhost", "localhost"),
        ("localhost:8001", "localhost"),
        ("[::1]:8001", "::1"),
        ("[::1]", "::1"),
        ("evil.example:8001", "evil.example"),
        ("[::1", ""),
        ("", ""),
    ],
)
def test_the_host_header_is_read_without_its_port(header, host):
    """An IPv6 literal without a port (`[::1]`) used to lose its last character and be
    refused; a broken one is never read as a local host."""
    assert host_name(header) == host


def test_a_foreign_host_never_reads_as_local():
    for header in ("evil.example", "evil.example:8001", "[2001:db8::1]:8001", "127.0.0.1.evil"):
        assert host_name(header) not in LOCAL_HOSTS
