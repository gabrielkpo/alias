"""Entry point of the standalone `alias-pii` executable (PyInstaller): the same command as the
installed one, `alias_pii.cli`."""

import sys

from alias_pii.cli import main

if __name__ == "__main__":
    sys.exit(main())
