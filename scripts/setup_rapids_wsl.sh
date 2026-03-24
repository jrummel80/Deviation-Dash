#!/usr/bin/env bash
set -euo pipefail

if ! command -v curl >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y curl bzip2 ca-certificates
fi

MINIFORGE_INSTALLER="Miniforge3-Linux-x86_64.sh"
MINIFORGE_URL="https://github.com/conda-forge/miniforge/releases/latest/download/${MINIFORGE_INSTALLER}"
MINIFORGE_DIR="$HOME/miniforge3"

if [[ ! -x "${MINIFORGE_DIR}/bin/conda" ]]; then
  curl -L "${MINIFORGE_URL}" -o "/tmp/${MINIFORGE_INSTALLER}"
  bash "/tmp/${MINIFORGE_INSTALLER}" -b -p "${MINIFORGE_DIR}"
fi

source "${MINIFORGE_DIR}/etc/profile.d/conda.sh"
conda config --set channel_priority flexible

if conda env list | awk '{print $1}' | grep -qx "rapids"; then
  conda env remove -n rapids -y
fi

conda create -n rapids -y -c rapidsai -c conda-forge python=3.11 cudf cuda-version=12.9
conda activate rapids

python - <<'PY'
import cudf
print("cuDF import OK")
print(cudf.Series([1, 2, 3]))
PY
