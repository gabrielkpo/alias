# Changelog

## [0.3.0](https://github.com/gabrielkpo/alias/compare/v0.2.0...v0.3.0) (2026-11-11)


### Features

* **onnx:** ONNX export and detector (the demo's model) ([#37](https://github.com/gabrielkpo/alias/issues/37)) ([79fbeff](https://github.com/gabrielkpo/alias/commit/79fbeff1c271cbf9e4263a6c245ecce3a4958be6))


### Bug Fixes

* **deps:** transformers 5 (&gt;=5.10), closing its security alerts ([#54](https://github.com/gabrielkpo/alias/issues/54)) ([fb34fe2](https://github.com/gabrielkpo/alias/commit/fb34fe2099f511d6b004090575ad77d7e58fafbf))


### Documentation

* **readme:** Mistral zero-shot baseline results ([#39](https://github.com/gabrielkpo/alias/issues/39)) ([1efe31e](https://github.com/gabrielkpo/alias/commit/1efe31ecf6fb62781c2c65bcb875c63b374d9dec))

## [0.2.0](https://github.com/gabrielkpo/alias/releases/tag/v0.2.0) (2026-11-11)


### Features

* **app:** local FastAPI to mask a pasted text ([#31](https://github.com/gabrielkpo/alias/issues/31)) ([7122301](https://github.com/gabrielkpo/alias/commit/7122301564a6bb219ab11a2cbbe56555298dada3))
* **app:** web page to paste a text and copy it masked ([#32](https://github.com/gabrielkpo/alias/issues/32)) ([fe7ad6f](https://github.com/gabrielkpo/alias/commit/fe7ad6f56438b9b19b952bbead15da9163672542))
* **benchmark:** harness with rules, Presidio and GLiNER baselines (step 3) ([#12](https://github.com/gabrielkpo/alias/issues/12)) ([e85a387](https://github.com/gabrielkpo/alias/commit/e85a3875cc103c5d27d6541b94749e27320d7635))
* **benchmark:** hybrid rules + GLiNER and Mistral zero-shot baselines ([#14](https://github.com/gabrielkpo/alias/issues/14)) ([162b7b7](https://github.com/gabrielkpo/alias/commit/162b7b7f7439c98fdbbe77bfd1794ed168fdc75c))
* **dataset:** grid generator, balancer, build command and datasheet (dataset v0.2, part 2) ([#10](https://github.com/gabrielkpo/alias/issues/10)) ([c617225](https://github.com/gabrielkpo/alias/commit/c617225cc3bc1d372428d16af4199e7c0d259162))
* **dataset:** identity factory and quality gates (dataset v0.2, part 1) ([#9](https://github.com/gabrielkpo/alias/issues/9)) ([720adaf](https://github.com/gabrielkpo/alias/commit/720adaf4554c0daade524b0903c906d08a6515cd))
* **dataset:** LLM-written documents and public corpora (dataset v0.3 and v0.4) ([#11](https://github.com/gabrielkpo/alias/issues/11)) ([4021ca5](https://github.com/gabrielkpo/alias/commit/4021ca52f4676d64f46cf3b352dcde7340f18bc2))
* **demo:** Hugging Face Space and model card, not published ([#35](https://github.com/gabrielkpo/alias/issues/35)) ([8eaabf2](https://github.com/gabrielkpo/alias/commit/8eaabf264e12a10d15f48281e9230649456b97ef))
* **demo:** put the values back in the LLM's answer ([#48](https://github.com/gabrielkpo/alias/issues/48)) ([e3c3eb3](https://github.com/gabrielkpo/alias/commit/e3c3eb360a996052b9dfc6aa0c58a75d4d262bc9))
* **demo:** run the detector in the browser on a static Hugging Face Space ([#41](https://github.com/gabrielkpo/alias/issues/41)) ([7a8ac62](https://github.com/gabrielkpo/alias/commit/7a8ac627df70bc41f1f31c21eedf51786a072514))
* **demo:** tell first visitors the model takes about 5 minutes to download ([#47](https://github.com/gabrielkpo/alias/issues/47)) ([04e39ae](https://github.com/gabrielkpo/alias/commit/04e39ae979fca47ffc54b8bef9ed5ee50a91b963))
* **detector:** add identifiers announced by a person's-file keyword ([#45](https://github.com/gabrielkpo/alias/issues/45)) ([ea952d9](https://github.com/gabrielkpo/alias/commit/ea952d913a6912466ddf1505bace1aaea666f553))
* **detector:** rules + model detector, step 5 ([#30](https://github.com/gabrielkpo/alias/issues/30)) ([28f25d1](https://github.com/gabrielkpo/alias/commit/28f25d1436344bf4ec10e9b174acaf597e71df6e))
* **docker:** CPU image of the API and page, tested on Actions ([#33](https://github.com/gabrielkpo/alias/issues/33)) ([d945e98](https://github.com/gabrielkpo/alias/commit/d945e9821891fcc0f1ec7166584091c77b685c21))
* **eval:** model choice for step 4, CPU latency and careful int8 modes ([#19](https://github.com/gabrielkpo/alias/issues/19)) ([52a4674](https://github.com/gabrielkpo/alias/commit/52a467488ef8fee2a48f92c14e467e2e4c976d11))
* **open-sets:** TAB as a realistic English test set ([#46](https://github.com/gabrielkpo/alias/issues/46)) ([072f8c8](https://github.com/gabrielkpo/alias/commit/072f8c8834f424a683425c4350f81541cb0efbfb))
* **readers:** read .txt, .md, .docx and text PDFs into plain text ([#5](https://github.com/gabrielkpo/alias/issues/5)) ([067acab](https://github.com/gabrielkpo/alias/commit/067acabb9aa3d0508ffaf0e955a02b90ce6f18d9))
* **rules:** FR + EN rule detector, stable alias masking and restoring ([#1](https://github.com/gabrielkpo/alias/issues/1)) ([b05e91b](https://github.com/gabrielkpo/alias/commit/b05e91b5e06f00afa99ce873db2b866164de91c2))
* **synthetic:** generate annotated French and English documents ([#7](https://github.com/gabrielkpo/alias/issues/7)) ([fa624b7](https://github.com/gabrielkpo/alias/commit/fa624b7fe16e29903f254a4e20eea4d95af3690e))
* **train:** fine-tuning command for the three candidates, heavy runs on GitHub CPU machines ([#15](https://github.com/gabrielkpo/alias/issues/15)) ([2e3cf94](https://github.com/gabrielkpo/alias/commit/2e3cf9461d529bd2163d7356aa57bef1cc87bc0c))


### Bug Fixes

* **ci:** compare index.html without what Hugging Face adds when serving it ([#50](https://github.com/gabrielkpo/alias/issues/50)) ([99f533c](https://github.com/gabrielkpo/alias/commit/99f533c9aa9d586cdeb4e76face960278c3a7169))
* **dataset:** LLM writer prompt v4 and two new gates, after a first run with the API ([#18](https://github.com/gabrielkpo/alias/issues/18)) ([92d4c82](https://github.com/gabrielkpo/alias/commit/92d4c82e4d5b52ede81c9028ca8dcb07ba0f86c2))
* **demo:** allow the runtime's blob module in the CSP ([#44](https://github.com/gabrielkpo/alias/issues/44)) ([c1f9624](https://github.com/gabrielkpo/alias/commit/c1f962451d37685c590b54d2d7db22a59f316ce0))
* **release:** tag as vX.Y.Z and align release-please config with secours-tech ([#4](https://github.com/gabrielkpo/alias/issues/4)) ([1f35b27](https://github.com/gabrielkpo/alias/commit/1f35b27044579ebc692e9f11e410cebddf737a45))
* **train:** gradient accumulation option, so mDeBERTa fits a T4 with the same batch ([#17](https://github.com/gabrielkpo/alias/issues/17)) ([6eacd2d](https://github.com/gabrielkpo/alias/commit/6eacd2da04917313763735e73e4dad4804d605be))
* **train:** turn off ModernBERT's compiled MLP, which crashes training on Kaggle GPUs ([#16](https://github.com/gabrielkpo/alias/issues/16)) ([fdfe69d](https://github.com/gabrielkpo/alias/commit/fdfe69d89ac6a4a623104abbf41fe54053b32d2b))


### Documentation

* **dataset:** specify how the training data is built, labelled and checked ([#8](https://github.com/gabrielkpo/alias/issues/8)) ([f5ea711](https://github.com/gabrielkpo/alias/commit/f5ea711c480ac4ed880c5102c4994e6cd3e59f2c))
* **open-sets:** TAB test results, read once ([#51](https://github.com/gabrielkpo/alias/issues/51)) ([d3e5229](https://github.com/gabrielkpo/alias/commit/d3e52294d70b8e089eb06a566f0202402bd82521))
* README as a project page with architecture, roadmap and evaluation plan ([#6](https://github.com/gabrielkpo/alias/issues/6)) ([f02fb7a](https://github.com/gabrielkpo/alias/commit/f02fb7a140429d0828454305b09375372690fbfc))
* **readme:** status banner reflects the trained model and its measured results ([#29](https://github.com/gabrielkpo/alias/issues/29)) ([5eaea35](https://github.com/gabrielkpo/alias/commit/5eaea35bc3d8f4c78d995c34bb9c782c65b1a446))
