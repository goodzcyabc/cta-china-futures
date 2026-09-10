"""命令行入口:cta research | cta live"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cta.config import load_config
from cta.data.source import RicequantParquetSource
from cta.instruments.specs import load_instruments

app = typer.Typer(add_completion=False, help="商品期货 CTA:研究回测与实盘出单")


@app.command()
def research(
    config: Path = typer.Option(Path("configs/strategy.yaml")),
    data: Path = typer.Option(Path("data/ricecta/data")),
    out: Path = typer.Option(Path("results")),
) -> None:
    """跑完整研究回测,结果写入 results/<config_digest>/。"""
    from cta.pipeline import run_research

    cfg = load_config(config)
    specs = load_instruments()
    src = RicequantParquetSource(data)
    out_dir = out / cfg.digest()
    meta = run_research(cfg, src, specs, out_dir)
    typer.echo(
        json.dumps(
            {k: meta[k] for k in ("config_digest", "git_sha", "n_symbols", "period")}, ensure_ascii=False
        )
    )
    for k, v in meta["stats"].items():
        typer.echo(f"  {k:14s} {v:.4f}" if isinstance(v, float) else f"  {k:14s} {v}")
    typer.echo(f"-> {out_dir}")


@app.command()
def live(
    asof: str = typer.Option(..., help="信号日 YYYY-MM-DD(用 <= 该日的数据)"),
    equity: float = typer.Option(..., help="当前权益(元)"),
    positions: Path = typer.Option(None, help="当前持仓 CSV: symbol,contract,lots"),
    config: Path = typer.Option(Path("configs/strategy.yaml")),
    data: Path = typer.Option(Path("data/ricecta/data")),
    out: Path = typer.Option(Path("results/live")),
) -> None:
    """按 as-of 日生成次日目标手数与订单差异,并留存输入快照。"""
    from cta.live.orders import generate_orders

    cfg = load_config(config)
    specs = load_instruments()
    src = RicequantParquetSource(data)
    report = generate_orders(cfg, src, specs, asof=asof, equity=equity, positions_csv=positions, out_dir=out)
    typer.echo(json.dumps(report["summary"], ensure_ascii=False, indent=2))


@app.command()
def report(run: Path = typer.Argument(..., help="results/<digest> 目录")) -> None:
    """从已完成的回测结果生成 report.md 与图。"""
    from cta.report.build import build_report

    typer.echo(f"-> {build_report(run)}")


if __name__ == "__main__":
    app()
