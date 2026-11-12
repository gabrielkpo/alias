"""The repository's own values stay fictitious (tests/README.md): every French phone number in a
tracked text file is in a range reserved for fiction, and every e-mail domain is reserved."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Ranges the French numbering plan keeps for fiction (tests/README.md).
FICTION = ("019900", "026191", "035301", "046571", "053649", "063998")
PHONE = re.compile(r"(?<![\w])(?:\+33[ .]?|0)([1-9])((?:[ .-]?\d{2}){4})(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,})")
RESERVED = ("example.com", "example.org", "example.net")
SKIPPED = (".lock", ".json", ".png", ".jpg", ".ico", ".onnx")


def tracked_texts():
    try:
        names = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout: the tracked files are unknown")
    for name in names:
        if name.endswith(SKIPPED):
            continue
        try:
            yield name, (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue


def test_phone_numbers_and_e_mail_domains_are_fictitious():
    found = []
    for name, text in tracked_texts():
        for number, line in enumerate(text.splitlines(), 1):
            for m in PHONE.finditer(line):
                if m.start() >= 2 and line[m.start() - 2].isdigit():  # an IBAN group, not a phone
                    continue
                digits = "0" + m.group(1) + re.sub(r"\D", "", m.group(2))
                if not digits.startswith(FICTION):
                    found.append(f"{name}:{number}: phone outside the fiction ranges")
            for m in EMAIL.finditer(line):
                domain = m.group(1).lower()
                if not (domain in RESERVED or domain.endswith((".example", ".invalid", ".test"))):
                    found.append(f"{name}:{number}: e-mail domain not reserved")
    assert found == []
