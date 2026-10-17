from alias_pii.benchmark import build
from alias_pii.latency import measure, pages


def test_pages_have_the_page_size():
    docs = [{"text": "a" * 2000}, {"text": "b" * 2000}, {"text": "c" * 2000}]
    cut = pages(docs, 10, size=1000)
    assert len(cut) == 6 and all(len(p) == 1000 for p in cut)


class Instant:
    def detect(self, text):
        return []


def test_measure_reports_and_passes():
    result = measure(Instant(), ["x"] * 13, warmup=3)
    assert result["pages"] == 10 and result["passes"]
    assert result["p95_s"] >= result["median_s"] >= 0


def test_build_named_methods():
    assert isinstance(build("fixed", {"fixed": Instant}), Instant)
