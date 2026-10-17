# Changelog

## [0.2.0](https://github.com/gabrielkpo/alias/compare/v0.1.0...v0.2.0) (2026-10-17)


### Features

* **benchmark:** harness with rules, Presidio and GLiNER baselines (step 3) ([#12](https://github.com/gabrielkpo/alias/issues/12)) ([e85a387](https://github.com/gabrielkpo/alias/commit/e85a3875cc103c5d27d6541b94749e27320d7635))
* **benchmark:** hybrid rules + GLiNER and Mistral zero-shot baselines ([#14](https://github.com/gabrielkpo/alias/issues/14)) ([162b7b7](https://github.com/gabrielkpo/alias/commit/162b7b7f7439c98fdbbe77bfd1794ed168fdc75c))
* **dataset:** grid generator, balancer, build command and datasheet (dataset v0.2, part 2) ([#10](https://github.com/gabrielkpo/alias/issues/10)) ([c617225](https://github.com/gabrielkpo/alias/commit/c617225cc3bc1d372428d16af4199e7c0d259162))
* **dataset:** identity factory and quality gates (dataset v0.2, part 1) ([#9](https://github.com/gabrielkpo/alias/issues/9)) ([720adaf](https://github.com/gabrielkpo/alias/commit/720adaf4554c0daade524b0903c906d08a6515cd))
* **dataset:** LLM-written documents and public corpora (dataset v0.3 and v0.4) ([#11](https://github.com/gabrielkpo/alias/issues/11)) ([4021ca5](https://github.com/gabrielkpo/alias/commit/4021ca52f4676d64f46cf3b352dcde7340f18bc2))
* **eval:** model choice for step 4, CPU latency and careful int8 modes ([#19](https://github.com/gabrielkpo/alias/issues/19)) ([52a4674](https://github.com/gabrielkpo/alias/commit/52a467488ef8fee2a48f92c14e467e2e4c976d11))
* **readers:** read .txt, .md, .docx and text PDFs into plain text ([#5](https://github.com/gabrielkpo/alias/issues/5)) ([067acab](https://github.com/gabrielkpo/alias/commit/067acabb9aa3d0508ffaf0e955a02b90ce6f18d9))
* **rules:** FR + EN rule detector, stable alias masking and restoring ([#1](https://github.com/gabrielkpo/alias/issues/1)) ([b05e91b](https://github.com/gabrielkpo/alias/commit/b05e91b5e06f00afa99ce873db2b866164de91c2))
* **synthetic:** generate annotated French and English documents ([#7](https://github.com/gabrielkpo/alias/issues/7)) ([fa624b7](https://github.com/gabrielkpo/alias/commit/fa624b7fe16e29903f254a4e20eea4d95af3690e))
* **train:** fine-tuning command for the three candidates, heavy runs on GitHub CPU machines ([#15](https://github.com/gabrielkpo/alias/issues/15)) ([2e3cf94](https://github.com/gabrielkpo/alias/commit/2e3cf9461d529bd2163d7356aa57bef1cc87bc0c))


### Bug Fixes

* **dataset:** LLM writer prompt v4 and two new gates, after a first run with the API ([#18](https://github.com/gabrielkpo/alias/issues/18)) ([92d4c82](https://github.com/gabrielkpo/alias/commit/92d4c82e4d5b52ede81c9028ca8dcb07ba0f86c2))
* **release:** tag as vX.Y.Z and align release-please config with secours-tech ([#4](https://github.com/gabrielkpo/alias/issues/4)) ([1f35b27](https://github.com/gabrielkpo/alias/commit/1f35b27044579ebc692e9f11e410cebddf737a45))
* **train:** gradient accumulation option, so mDeBERTa fits a T4 with the same batch ([#17](https://github.com/gabrielkpo/alias/issues/17)) ([6eacd2d](https://github.com/gabrielkpo/alias/commit/6eacd2da04917313763735e73e4dad4804d605be))
* **train:** turn off ModernBERT's compiled MLP, which crashes training on Kaggle GPUs ([#16](https://github.com/gabrielkpo/alias/issues/16)) ([fdfe69d](https://github.com/gabrielkpo/alias/commit/fdfe69d89ac6a4a623104abbf41fe54053b32d2b))


### Documentation

* **dataset:** specify how the training data is built, labelled and checked ([#8](https://github.com/gabrielkpo/alias/issues/8)) ([f5ea711](https://github.com/gabrielkpo/alias/commit/f5ea711c480ac4ed880c5102c4994e6cd3e59f2c))
* README as a project page with architecture, roadmap and evaluation plan ([#6](https://github.com/gabrielkpo/alias/issues/6)) ([f02fb7a](https://github.com/gabrielkpo/alias/commit/f02fb7a140429d0828454305b09375372690fbfc))
