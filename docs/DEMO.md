# Public demo: Hugging Face Space

The demo shows Alias in a few seconds without installing anything. It is the same API and page as
the Docker image, started with `--demo`: a banner asks for fictitious data only, a text is limited
to 5,000 characters, nothing is logged or stored. Real documents belong on the user's own machine.

**Publishing needs Gabriel's explicit agreement** (docs/TRAINING.md, Publication): the model goes
public on Hugging Face, which cannot really be undone. Nothing below has been run yet.

## Steps (once agreed)

1. Check the model can be published: trained on synthetic and public data only (never
   `data/real/`), base model licence compatible (`jhu-clsp/mmBERT-small`: MIT, checked 11/11), WikiNER attribution in the card.
2. Create the model repository on Hugging Face and upload the checkpoint (`final/` from the
   `alias-train-mmbert-small` Kaggle kernel) with `docs/MODEL_CARD.md` as its `README.md`.
3. Create a Docker Space and push the two files of `space/` (`README.md`, `Dockerfile`).
4. In the Space settings, set the variables `ALIAS_REF` (a release tag or commit of this
   repository) and `MODEL_REPO` (the model id from step 2). They are passed as build arguments.
5. Check the Space: the banner shows, an example is masked, `/health` reports `rules+model`.
6. Add the demo link to the README.

The Space builds the code from GitHub and downloads the model at build time only; at run time
`HF_HUB_OFFLINE` is set and the process makes no outgoing call.
