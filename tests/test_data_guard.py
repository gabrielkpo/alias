"""Text leaves the machine (an API benchmark, training) only from the project's synthetic,
LLM-written and public data folders, or a dataset build_dataset wrote: an allow list, so real
documents in a folder of any name stay home."""

from pathlib import Path

from alias_pii.data_guard import built_dataset, shareable


def test_only_the_shareable_data_folders_qualify(tmp_path):
    for name in ("data/synthetic", "data/llm", "data/open/tab"):
        assert shareable(tmp_path / name, root=tmp_path), name
    for name in ("data/real", "data/raw", "documents", "data/synthetic-copy", "data"):
        assert not shareable(tmp_path / name, root=tmp_path), name
    assert not shareable(Path("/tmp/clients"), root=tmp_path)


def test_a_dataset_elsewhere_must_be_one_build_dataset_wrote(tmp_path):
    assert not built_dataset(tmp_path)
    (tmp_path / "DATASHEET.md").write_text("synthetic", encoding="utf-8")
    assert built_dataset(tmp_path)
