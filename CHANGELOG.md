# Changelog

## [0.4.0](https://github.com/gabrielkpo/alias/compare/v0.3.0...v0.4.0) (2026-11-13)


### Features

* **bridge:** a container image for alias-pii serve ([#80](https://github.com/gabrielkpo/alias/issues/80)) ([eee5eee](https://github.com/gabrielkpo/alias/commit/eee5eee8fc1870c3b778b9cc436fea22f63dda50))
* **bridge:** a local token when the bridge holds the Mistral key ([#79](https://github.com/gabrielkpo/alias/issues/79)) ([5618255](https://github.com/gabrielkpo/alias/commit/56182553dd35ae65eac570515f7bfc848f823326))
* **bridge:** accept streamed requests, restored whole then sent as events ([#76](https://github.com/gabrielkpo/alias/issues/76)) ([82c5e44](https://github.com/gabrielkpo/alias/commit/82c5e441aa8d0f78477919ce52b15113b7f976f6))
* **bridge:** local Mistral-compatible endpoint that masks and restores ([#58](https://github.com/gabrielkpo/alias/issues/58)) ([0346204](https://github.com/gabrielkpo/alias/commit/0346204bfe59dc0a477fa6f20757f821db6237ea))
* **bridge:** measure the bridge against the real Mistral API ([#81](https://github.com/gabrielkpo/alias/issues/81)) ([63282d8](https://github.com/gabrielkpo/alias/commit/63282d8f47b9b196e1e8ce032d54d0c97228bd89))
* **cli:** alias-pii serve, the Mistral key in the OS keychain ([#77](https://github.com/gabrielkpo/alias/issues/77)) ([c0f55d2](https://github.com/gabrielkpo/alias/commit/c0f55d20a03bb06ce6477d1cff3d96b74daeba69))
* **desktop:** a first-launch setup and a clearer window ([#89](https://github.com/gabrielkpo/alias/issues/89)) ([a9a3434](https://github.com/gabrielkpo/alias/commit/a9a34340e2bb339b667c942933082b12c02274d0))
* **desktop:** Alias as a macOS app (Tauri), built and launched in CI ([#86](https://github.com/gabrielkpo/alias/issues/86)) ([9405782](https://github.com/gabrielkpo/alias/commit/940578228e8eddae6b9f7339b6c2cfce7512491b))
* **desktop:** the app's own blue instead of orange ([#90](https://github.com/gabrielkpo/alias/issues/90)) ([69dd17c](https://github.com/gabrielkpo/alias/commit/69dd17c06d8d3967e7da04241b3d111e3e907b96))
* **release:** attach the macOS app to each release ([#87](https://github.com/gabrielkpo/alias/issues/87)) ([a1c767b](https://github.com/gabrielkpo/alias/commit/a1c767b6abe9c217004c113dde0a745f5706e381))


### Bug Fixes

* **bridge:** forward nothing unmasked, never restore values into links ([#60](https://github.com/gabrielkpo/alias/issues/60)) ([3b44f63](https://github.com/gabrielkpo/alias/commit/3b44f631e44da192af7bb29843eb789b255141c6))
* **bridge:** gateway errors, body cap, answers in parts ([#65](https://github.com/gabrielkpo/alias/issues/65)) ([d341a5e](https://github.com/gabrielkpo/alias/commit/d341a5e1d922eb70caef56b9f1b0bfb7551fc501))
* **bridge:** give every occurrence of an aliased value the same alias ([#62](https://github.com/gabrielkpo/alias/issues/62)) ([4bd07d9](https://github.com/gabrielkpo/alias/commit/4bd07d98730999c1593c11a3fa9d93593abb0054))
* **bridge:** keep Mistral's gzip answers intact in the measure ([#83](https://github.com/gabrielkpo/alias/issues/83)) ([3217c9d](https://github.com/gabrielkpo/alias/commit/3217c9d5eb86127085e514392585f849940c8650))
* **bridge:** refuse to start without a model unless --rules-only ([#61](https://github.com/gabrielkpo/alias/issues/61)) ([f99e3fa](https://github.com/gabrielkpo/alias/commit/f99e3fa53edb5a64e2bd103f5d4359f5ba7a2846))
* **bridge:** run the measure in one event loop ([#82](https://github.com/gabrielkpo/alias/issues/82)) ([30ca330](https://github.com/gabrielkpo/alias/commit/30ca3300a726703d8c4360a25ccd56deda188809))
* **desktop:** sign the app without the hardened runtime so its bridge starts ([#88](https://github.com/gabrielkpo/alias/issues/88)) ([9ab431d](https://github.com/gabrielkpo/alias/commit/9ab431d5516ef4555c39178cc37a7f2d1b8360be))
* **masking:** keep e-mails and identifiers apart when a dot or dash differs ([#64](https://github.com/gabrielkpo/alias/issues/64)) ([77b7ab7](https://github.com/gabrielkpo/alias/commit/77b7ab73470e1b072d26cf775ce657ad56c99802))
* **masking:** one alias for a UK or US phone found by the model ([#72](https://github.com/gabrielkpo/alias/issues/72)) ([f83a218](https://github.com/gabrielkpo/alias/commit/f83a218323cb5b47e530cf8ae1dfca15e02f1cbe))
* **masking:** restore aliases an LLM rewrote in another case or form ([#75](https://github.com/gabrielkpo/alias/issues/75)) ([08be5ec](https://github.com/gabrielkpo/alias/commit/08be5ec5e52098f1ebdc51afe1b451b84a160320))
* **masking:** take values from the text, keep the masked text out of repr ([#70](https://github.com/gabrielkpo/alias/issues/70)) ([b81edb6](https://github.com/gabrielkpo/alias/commit/b81edb6158b2a93ace795d0e1c7e5ada7838a827))
* **rules:** read a file number when one word qualifies the keyword ([#71](https://github.com/gabrielkpo/alias/issues/71)) ([83735b4](https://github.com/gabrielkpo/alias/commit/83735b4c637405e11835ebd8a04e400cd65ea9fe))
* **rules:** read through typographic spaces and invisible characters ([#63](https://github.com/gabrielkpo/alias/issues/63)) ([97fb597](https://github.com/gabrielkpo/alias/commit/97fb5971e637b2038e38c7540435990549184585))


### Documentation

* **bridge:** record the first measure against the real Mistral API ([#84](https://github.com/gabrielkpo/alias/issues/84)) ([60b4f9a](https://github.com/gabrielkpo/alias/commit/60b4f9ade996cd326270eede32632eb952b2788b))
* bring the README up to date with main ([#68](https://github.com/gabrielkpo/alias/issues/68)) ([ce00de3](https://github.com/gabrielkpo/alias/commit/ce00de3ec2551c81597682775abe238e84c5610b))
* refresh stale docs and rewrite working notes as neutral records ([#69](https://github.com/gabrielkpo/alias/issues/69)) ([7249505](https://github.com/gabrielkpo/alias/commit/724950551d5b4acefdf5ccedc5caea2699bfaca2))

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
