#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "[runtime-sync] macOS is required" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cli_root="$repo_root/cli"
uv_bin="${UV:-$(command -v uv || true)}"

if [[ -z "$uv_bin" ]]; then
  echo "[runtime-sync] uv is required" >&2
  exit 1
fi

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/elevate-mac-runtime.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT
requirements="$tmp_dir/requirements.txt"

(
  cd "$cli_root"
  "$uv_bin" export \
    --quiet \
    --frozen \
    --extra web \
    --no-dev \
    --no-emit-project \
    --output-file "$requirements"
)

for arch in arm64 x64; do
  runtime_root="$repo_root/desktop/runtime/$arch/python"
  runtime_python="$runtime_root/bin/python3.12"
  if [[ ! -x "$runtime_python" ]]; then
    echo "[runtime-sync] missing $arch interpreter: $runtime_python" >&2
    exit 1
  fi

  echo "[runtime-sync] syncing $arch from cli/uv.lock"
  "$uv_bin" pip install \
    --quiet \
    --python "$runtime_python" \
    --requirements "$requirements" \
    --require-hashes \
    --strict \
    --link-mode copy \
    --no-python-downloads

  "$runtime_python" -I -B -m pip check
done

runtime_dir="$repo_root/desktop/runtime"
find "$runtime_dir" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$runtime_dir" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.DS_Store' \) -delete

echo "[runtime-sync] arm64 and x64 dependency closures pass"
