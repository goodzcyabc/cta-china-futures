from cta.instruments.specs import load_instruments


def test_load_and_costs() -> None:
    t = load_instruments()
    assert len(t.specs) == 58 and t.verified and t.verified_date == "2026-09-11"
    cu = t["cu"]
    assert cu.exchange == "SHFE" and cu.multiplier == 5
    # 铜 70000 元/吨 × 5 吨 = 35 万名义;保证金 11%(2026-07-02 起) = 3.85 万;手续费万 0.5 = 17.5 元;1 跳滑点 = 10 元 × 5 = 50 元
    assert cu.notional(70000, 1) == 350_000
    assert abs(cu.margin(70000, 2) - 77_000) < 1e-9
    assert abs(cu.fee(70000, 1) - 17.5) < 1e-9
    assert cu.slippage(1, 1) == 50
    c = t["C"]
    assert c.fee(2500, 3) == 3 * 1.2 and c.fee_notional_bp == 0
    ma = t["MA"]  # 甲醇按成交金额万分之一(核验前误记为 2 元/手)
    assert ma.fee_per_lot == 0 and abs(ma.fee(2500, 1) - 2.5) < 1e-9
    assert "TF" not in t.symbols({"agri", "chem", "energy", "ferrous", "metal", "precious"})
    assert (
        len(t.symbols({"agri", "chem", "energy", "ferrous", "metal", "precious"}, verified_only=True)) == 22
    )


def test_every_symbol_has_provenance_and_digest_is_stable() -> None:
    t = load_instruments()
    for s, sp in t.specs.items():
        if not sp.verified:
            continue  # 研究用占位品种(design_log 十一 E1)不要求来源 URL
        assert sp.source.startswith("http"), s
        assert len(sp.effective) == 10, s
        assert (sp.fee_per_lot > 0) != (sp.fee_notional_bp > 0), f"{s}: 手续费口径必须二选一"
    d = t.digest()
    assert len(d) == 8 and d == load_instruments().digest()
