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


def test_quantize_modes_choose_layers():
    from alias_pii.train import _quantized

    assert _quantized("classifier", "all")
    assert not _quantized("classifier", "no-head") and _quantized(
        "model.layers.0.attn.Wqkv", "no-head"
    )
    assert _quantized("model.layers.0.mlp.Wi", "mlp") and not _quantized(
        "model.layers.0.attn.Wqkv", "mlp"
    )
    assert _quantized("roberta.encoder.layer.0.output.dense", "mlp")
    assert not _quantized("roberta.encoder.layer.0.attention.output.dense", "mlp")
