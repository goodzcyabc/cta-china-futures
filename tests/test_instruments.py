from cta.instruments.specs import load_instruments


def test_load_and_costs() -> None:
    t = load_instruments()
    assert len(t.specs) == 23 and not t.verified
    cu = t["cu"]
    assert cu.exchange == "SHFE" and cu.multiplier == 5
    # 铜 70000 元/吨 × 5 吨 = 35 万名义;保证金 10% = 3.5 万;手续费万 0.5 = 17.5 元;1 跳滑点 = 10 元 × 5 = 50 元
    assert cu.notional(70000, 1) == 350_000
    assert abs(cu.margin(70000, 2) - 70_000) < 1e-9
    assert abs(cu.fee(70000, 1) - 17.5) < 1e-9
    assert cu.slippage(1, 1) == 50
    c = t["C"]
    assert c.fee(2500, 3) == 3 * 1.2 and c.fee_notional_bp == 0
    assert "TF" not in t.symbols({"agri", "chem", "energy", "ferrous", "metal", "precious"})
    assert len(t.symbols({"agri", "chem", "energy", "ferrous", "metal", "precious"})) == 22
