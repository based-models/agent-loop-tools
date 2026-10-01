#!/usr/bin/env bash
# Build the sdist + wheel, install the wheel into a BARE virtualenv (dependencies come
# from PyPI, like a real consumer's install) and prove it works there.
set -euo pipefail
cd "$(dirname "$0")/.."

export PIP_DISABLE_PIP_VERSION_CHECK=1
PY=${PYTHON:-python3}
# Where the wheel's agentloop dependency comes from. Defaults to PyPI. Before
# based-models-agentloop is published, point this at a local wheel or checkout.
AGENTLOOP=${AGENTLOOP_REQUIREMENT:-}

rm -rf dist
"$PY" -m build >/dev/null
"$PY" -m twine check dist/*

whl=$(ls dist/based_models_agentloop_tools-*.whl)
sdist=$(ls dist/based_models_agentloop_tools-*.tar.gz)

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
"$PY" -m venv "$tmp/venv"
[ -n "$AGENTLOOP" ] && "$tmp/venv/bin/pip" install -q "$AGENTLOOP"
"$tmp/venv/bin/pip" install -q "$whl"

"$tmp/venv/bin/python" - <<'PY'
import sys
from importlib.metadata import version

import agentloop_tools
from agentloop_tools.web import DomainPolicy, native_web_search, sources  # noqa: F401

assert agentloop_tools.__version__ == version("based-models-agentloop-tools"), \
    "__version__ and pyproject.toml disagree"
tool = native_web_search(allowed_domains=["example.com"])
assert tool.kind == "web_search"
for vendor in ("anthropic", "httpx", "opentelemetry"):
    assert vendor not in sys.modules, f"importing agentloop_tools loaded {vendor}"
print("ok: the installed wheel works and stays light")
PY

contents=$(unzip -Z1 "$whl")
grep -qx "agentloop_tools/py.typed" <<<"$contents" && echo "ok: py.typed shipped"
grep -q "dist-info/licenses/LICENSE$" <<<"$contents" || { echo "FAIL: LICENSE missing"; exit 1; }
meta=$(unzip -p "$whl" '*.dist-info/METADATA')
grep -q "^License-Expression: Apache-2.0" <<<"$meta" || { echo "FAIL: license metadata"; exit 1; }
grep -q "Private :: Do Not Upload" <<<"$meta" && { echo "FAIL: Private classifier"; exit 1; }

for archive in wheel sdist; do
    if [ "$archive" = wheel ]; then listing=$contents; else listing=$(tar tzf "$sdist"); fi
    if grep -E '(^|/)(tests|scripts|docs|experiments|\.github)/|DESIGN\.md' <<<"$listing"; then
        echo "FAIL: unexpected files in the $archive"; exit 1
    fi
done
echo "ok: the wheel and sdist contain the package and nothing else"
