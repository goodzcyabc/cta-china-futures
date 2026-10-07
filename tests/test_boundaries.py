"""生产代码(src/cta)与研究代码(research/cta_research)的边界。

生产代码不导入研究代码;唯一例外是 `cta.pipeline._extra_factors_of` 在配置启用 msf 时按需加载多源合成因子。
研究代码可以导入生产代码(用同一条数据、信号、引擎路径评价候选)。
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {("cta/pipeline.py", "_extra_factors_of")}


def _research_imports(path: Path) -> list[tuple[str, str]]:
    """(所在函数名或 <module>, 被导入的模块) —— 只列出 cta_research 的导入。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, func: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, child.name)
                continue
            mods: list[str] = []
            if isinstance(child, ast.Import):
                mods = [a.name for a in child.names]
            elif isinstance(child, ast.ImportFrom) and child.module:
                mods = [child.module]
            found.extend((func, m) for m in mods if m.split(".")[0] == "cta_research")
            visit(child, func)

    visit(tree, "<module>")
    return found


def _production_files() -> list[Path]:
    """生产代码:src/cta 全部模块 + scripts/ 下的运维脚本。"""
    return sorted((ROOT / "src" / "cta").rglob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))


def test_production_does_not_import_research() -> None:
    files = _production_files()
    assert len(files) > 40, len(files)  # 路径写错时不能空跑通过
    bad, allowed_seen = [], set()
    for p in files:
        rel = p.relative_to(ROOT / "src").as_posix() if p.is_relative_to(ROOT / "src") else p.name
        for func, mod in _research_imports(p):
            if (rel, func) in ALLOWED:
                allowed_seen.add((rel, func))
            else:
                bad.append(f"{rel}:{func} imports {mod}")
        # importlib.import_module("cta_research...") 之类的字符串导入:研究包名只许出现在允许的文件里
        if "cta_research" in p.read_text(encoding="utf-8") and rel not in {f for f, _ in ALLOWED}:
            bad.append(f"{rel} mentions cta_research")
    assert not bad, bad
    assert allowed_seen == ALLOWED, allowed_seen  # 唯一的例外确实存在(检查本身在起作用)


def test_production_imports_without_research_on_path() -> None:
    """导入路径里只有 src/、没有 research/ 时(纸面每日任务就是这样跑的),生产入口全部能导入,且不会加载研究代码。"""
    research = str(ROOT / "research")
    code = "\n".join(
        [
            "import sys",
            "import os",
            f"sys.path = [p for p in sys.path if os.path.realpath(p or '.') != os.path.realpath({research!r})]",
            f"sys.path.insert(0, {str(ROOT / 'src')!r})",
            "import cta.cli, cta.pipeline, cta.paper.runner, cta.live.orders, cta.report.build",
            "import cta.analysis.paper_acceptance, cta.analysis.attribution, cta.analysis.loo, cta.analysis.stats",
            "assert not [m for m in sys.modules if m.startswith('cta_research')], 'research imported'",
            "import importlib.util",
            "assert importlib.util.find_spec('cta_research') is None, 'research still on path'",
        ]
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=False)
    assert out.returncode == 0, out.stderr
