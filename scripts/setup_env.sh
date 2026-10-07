#!/bin/bash
# 创建项目环境:.venv(Python 3.12)+ requirements-dev.txt,并把 src/ 加入环境的导入路径(之后不需要 PYTHONPATH)。
# 用法:scripts/setup_env.sh [python3.12 的路径]
set -euo pipefail
cd "$(dirname "$0")/.."
PY312="${1:-$(command -v python3.12 || true)}"
if [ -z "$PY312" ]; then echo "需要 Python 3.12(例如 brew install python@3.12 或 uv python install 3.12)" >&2; exit 1; fi
"$PY312" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements-dev.txt
SITE=$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
printf '%s\n' "$PWD/src" > "$SITE/cta_repo.pth"
.venv/bin/python -c "import cta, sys; print('ok:', sys.version.split()[0], cta.__file__)"
