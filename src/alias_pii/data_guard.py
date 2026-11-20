"""Where text may leave the machine: to a third-party API (the `mistral` benchmark method) or
into training. Only the project's synthetic, LLM-written and public data folders qualify, named
from the working directory; a training folder elsewhere (a Kaggle input) must be a dataset
`build_dataset` wrote, which carries its DATASHEET.md. A folder holding real documents, under
any name, is refused: the check is an allow list, not a guess on the folder's name."""

from __future__ import annotations

from pathlib import Path

SHAREABLE = ("data/synthetic", "data/llm", "data/open")


def shareable(path: Path, root: Path | None = None) -> bool:
    """Whether `path` is one of the shareable data folders (or inside one)."""
    base = (root or Path.cwd()).resolve()
    target = path.resolve()
    folders = [(base / name).resolve() for name in SHAREABLE]
    return any(target == folder or folder in target.parents for folder in folders)


def built_dataset(path: Path) -> bool:
    """Whether `path` is a synthetic dataset written by `build_dataset` (it has DATASHEET.md)."""
    return (path / "DATASHEET.md").is_file()
