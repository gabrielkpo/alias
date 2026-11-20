#!/bin/sh
# Installs this project with the versions of uv.lock, checked against its hashes, into the
# current Python: what the Docker image does, for CI jobs that need PyTorch. PyTorch is the
# CPU-only build of the locked version, from the PyTorch index: the CUDA build and its nvidia,
# cuda and triton packages are several GB a CPU job does not need.
#   sh packaging/install-locked.sh --extra model --group data
set -eu
pip install -q "uv==0.13.7"
gpu=$(uv export --frozen --no-dev "$@" --no-emit-project --no-hashes \
  | grep -oE '^(nvidia-[a-z0-9-]+|cuda-[a-z0-9-]+|triton)==' | sed 's/==$//; s/^/--no-emit-package /')
# shellcheck disable=SC2086
uv export --frozen --no-dev "$@" --no-emit-project --no-emit-package torch $gpu -o requirements.txt
pip install -q --require-hashes -r requirements.txt
torch=$(uv export --frozen --no-dev "$@" --no-emit-project --no-hashes | sed -n 's/^torch==\([^ ;]*\).*/\1/p')
if [ -n "$torch" ]; then
  pip install -q --no-deps --index-url https://download.pytorch.org/whl/cpu "torch==${torch}"
fi
pip install -q --no-deps -e .
rm -f requirements.txt
