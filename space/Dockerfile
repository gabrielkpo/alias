# Hugging Face Space (Docker SDK) for the public demo. Builds the released code and downloads the
# published model once, at build time; at run time nothing is downloaded and nothing is logged.
# Space variables (passed as build arguments): ALIAS_REF (git tag or commit of the code) and
# MODEL_REPO (Hugging Face model id). See docs/DEMO.md.
FROM python:3.12-slim

ARG ALIAS_REF
ARG MODEL_REPO
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 HF_HUB_DISABLE_TELEMETRY=1

RUN test -n "$ALIAS_REF" && test -n "$MODEL_REPO"
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.3" \
    && pip install "alias-pii[app,model] @ git+https://github.com/gabrielkpo/alias@${ALIAS_REF}" \
       "huggingface_hub>=0.24"

# Spaces run as user 1000.
RUN useradd --create-home --uid 1000 user
USER user
WORKDIR /home/user
RUN python -c "from huggingface_hub import snapshot_download; \
snapshot_download('${MODEL_REPO}', local_dir='/home/user/model')"

ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 8000
# Demo limits: banner asking for fictitious data, 5,000 characters (about two pages) per text.
CMD ["python", "-m", "alias_pii.app", "--host", "0.0.0.0", "--port", "8000", \
     "--model", "/home/user/model", "--demo", "--max-chars", "5000"]
