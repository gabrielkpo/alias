# Test fixtures

Alias handles personal data, so every value in the tests must be fictitious **and** unable to
reach a real person. Use only:

| Kind | Source |
|---|---|
| E-mail | domains reserved by RFC 2606: `example.com`, `example.org`, `example.net`, any `*.example` |
| French phone | ranges reserved for fiction by the French numbering plan: `01 99 00`, `02 61 91`, `03 53 01`, `04 65 71`, `05 36 49`, `06 39 98` (libphonenumber rejects `06 39 98` as unallocated, so detection tests use `01 99 00`) |
| UK phone | Ofcom drama ranges, e.g. `020 7946 0000`-`0999`, `07700 900000`-`900999` |
| US phone | `555-0100`-`555-0199` |
| IBAN | published specification examples (`FR76 3000 6000 0112 3456 7890 189`, `GB82 WEST 1234 5698 7654 32`, `DE89 3704 0044 0532 0130 00`) |
| NIR | invented, with the key computed for the test |
| US SSN | `123-45-6789`, the usual sample number |

Real annotated texts never go in this repository (see `.gitignore`: `data/real/`).
