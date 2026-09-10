from cta.config import StrategyConfig, load_config


def test_load_and_digest_stable() -> None:
    c = load_config()
    assert c.portfolio.target_vol == 0.10 and c.execution.fill == "next_open"
    d1 = c.digest()
    c2 = StrategyConfig(**c.model_dump())
    assert c2.digest() == d1 and len(d1) == 12
    c3 = c.model_copy(update={"version": "0.1.1"})
    assert c3.digest() != d1
