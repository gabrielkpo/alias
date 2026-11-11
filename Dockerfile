# Alias, CPU image: the local API and its page, rules + model.
#
#   docker build -t alias .
#   docker run --rm -p 127.0.0.1:8000:8000 -v "$PWD/models/mmbert-small/final:/model:ro" alias
#
# The fine-tuned checkpoint is mounted at /model (read-only); without it only the rules run.
# Nothing is downloaded at run time: Hugging Face libraries are set offline.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    ALIAS_MODEL=/model

WORKDIR /app
# CPU-only PyTorch: the CUDA build is several GB the image does not need.
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.3"
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[app,model]" && rm -rf /app/src

RUN useradd --create-home --uid 10001 alias
USER alias
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
# Listens on every interface inside the container; publish it on 127.0.0.1 only (see above).
CMD ["sh", "-c", "if [ -f \"$ALIAS_MODEL/config.json\" ]; then exec python -m alias_pii.app --host 0.0.0.0 --model \"$ALIAS_MODEL\"; else exec python -m alias_pii.app --host 0.0.0.0 --model ''; fi"]
