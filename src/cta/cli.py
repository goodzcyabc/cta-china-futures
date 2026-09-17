"""命令行入口:cta research | cta live"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cta.config import load_config
from cta.data.source import DataSource, RicequantParquetSource
from cta.instruments.specs import load_instruments

app = typer.Typer(add_completion=False, help="商品期货 CTA:研究回测与实盘出单")


def _make_source(source: str, data: Path) -> DataSource:
    """ricequant:米筐导出;exchange:交易所直连;stitched:米筐历史 + 交易所增量(默认)。"""
    if source == "ricequant":
        return RicequantParquetSource(data)
    if source == "exchange":
        from cta.data.exchanges.source import ExchangeSource

        return ExchangeSource()
    if source == "stitched":
        from cta.data.exchanges.source import default_stitched

        return default_stitched(data)
    raise typer.BadParameter(f"unknown source {source}")


@app.command()
def research(
    config: Path = typer.Option(Path("configs/strategy.yaml")),
    data: Path = typer.Option(Path("data/ricecta/data")),
    out: Path = typer.Option(Path("results")),
    source: str = typer.Option("stitched", help="ricequant | exchange | stitched"),
    end: str = typer.Option(None, help="回测截止日(默认到数据末尾)"),
) -> None:
    """跑完整研究回测,结果写入 results/<config_digest>_<instruments_digest>[_<source>]/。"""
    from cta.pipeline import run_research

    cfg = load_config(config)
    specs = load_instruments()
    src = _make_source(source, data)
    suffix = "" if source == "ricequant" else f"_{source}"
    out_dir = out / f"{cfg.digest()}_{specs.digest()}{suffix}"
    if end:
        cfg = cfg.model_copy(update={"backtest": cfg.backtest.model_copy(update={"end": end})})
    meta = run_research(cfg, src, specs, out_dir)
    typer.echo(
        json.dumps(
            {k: meta[k] for k in ("config_digest", "instruments_digest", "git_sha", "n_symbols", "period")},
            ensure_ascii=False,
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
    source: str = typer.Option("stitched", help="ricequant | exchange | stitched"),
) -> None:
    """按 as-of 日生成次日目标手数与订单差异,并留存输入快照。"""
    from cta.live.orders import generate_orders

    cfg = load_config(config)
    specs = load_instruments()
    src = _make_source(source, data)
    report = generate_orders(cfg, src, specs, asof=asof, equity=equity, positions_csv=positions, out_dir=out)
    typer.echo(json.dumps(report["summary"], ensure_ascii=False, indent=2))


@app.command()
def report(run: Path = typer.Argument(..., help="results/<digest> 目录")) -> None:
    """从已完成的回测结果生成 report.md 与图。"""
    from cta.report.build import build_report

    typer.echo(f"-> {build_report(run)}")


if __name__ == "__main__":
    app()


@app.command()
def paper(
    action: str = typer.Argument(..., help="step | catchup | status"),
    date: str = typer.Option(None, help="交易日(默认今天)"),
    no_ingest: bool = typer.Option(False, help="不拉交易所数据,只用已落盘的数据"),
) -> None:
    """纸面交易:step 处理单个交易日(拉数据 → 成交昨日订单并盯市 → 生成今日订单);catchup 补跑到指定日;status 打印账本。"""
    import pandas as pd

    from cta.paper import runner
    from cta.paper.book import PaperBook

    d = pd.Timestamp(date) if date else pd.Timestamp.today().normalize()
    if action == "step":
        typer.echo(
            json.dumps(runner.step(d, do_ingest=not no_ingest), ensure_ascii=False, indent=1, default=str)
        )
    elif action == "catchup":
        for log in runner.catchup(d, do_ingest=not no_ingest):
            typer.echo(json.dumps(log, ensure_ascii=False, default=str))
    elif action == "status":
        typer.echo(PaperBook().state.to_json())
    else:
        raise typer.BadParameter(action)
