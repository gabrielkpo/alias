# Alias, CPU image: the local API and its page, rules + model.
#
#   docker build -t alias .
#   docker run --rm -p 127.0.0.1:8000:8000 -v "$PWD/models/mmbert-small/final:/model:ro" alias
#
# The fine-tuned checkpoint is mounted at /model (read-only); without it only the rules run.
# Nothing is downloaded at run time: Hugging Face libraries are set offline.
# Base image pinned by digest: a rebuild gets the same system, until this line changes.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    ALIAS_MODEL=/model

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# The versions of uv.lock, checked against its hashes. PyTorch is the CPU-only build of the
# locked version, from the PyTorch index: the CUDA build and its nvidia, cuda and triton packages
# are several GB the image does not need, so they are left out of the export.
RUN pip install "uv==0.13.7" \
    && GPU=$(uv export --frozen --no-dev --extra app --extra model --no-emit-project --no-hashes \
        | grep -oE '^(nvidia-[a-z0-9-]+|cuda-[a-z0-9-]+|triton)==' \
        | sed 's/==$//; s/^/--no-emit-package /') \
    && uv export --frozen --no-dev --extra app --extra model --no-emit-project \
        --no-emit-package torch $GPU -o requirements.txt \
    && pip install --require-hashes -r requirements.txt \
    && TORCH=$(uv export --frozen --no-dev --extra model --no-emit-project --no-hashes \
        | sed -n 's/^torch==\([^ ;]*\).*/\1/p') \
    && pip install --no-deps --index-url https://download.pytorch.org/whl/cpu "torch==${TORCH}" \
    && pip install --no-deps . \
    && pip uninstall -y uv && rm -rf /app/src requirements.txt

RUN useradd --create-home --uid 10001 alias
USER alias
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
# Listens on every interface inside the container; publish it on 127.0.0.1 only (see above).
CMD ["sh", "-c", "if [ -f \"$ALIAS_MODEL/config.json\" ]; then exec python -m alias_pii.app --host 0.0.0.0 --model \"$ALIAS_MODEL\"; else exec python -m alias_pii.app --host 0.0.0.0 --model ''; fi"]
