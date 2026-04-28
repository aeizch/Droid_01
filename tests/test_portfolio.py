from quant.portfolio.portfolio import Portfolio


def test_open_and_close_position_tracks_pnl():
    pf = Portfolio()
    pf.on_fill("BTCUSDT", "BUY", qty=1.0, price=100.0)
    assert pf.has_position("BTCUSDT")
    pf.on_fill("BTCUSDT", "SELL", qty=1.0, price=110.0)
    assert not pf.has_position("BTCUSDT")
    assert pf.realised_pnl == 10.0
    assert pf.daily_pnl == 10.0


def test_average_price_on_position_increase():
    pf = Portfolio()
    pf.on_fill("BTCUSDT", "BUY", qty=1.0, price=100.0)
    pf.on_fill("BTCUSDT", "BUY", qty=1.0, price=120.0)
    pos = pf.positions["BTCUSDT"]
    assert pos.qty == 2.0
    assert abs(pos.avg_price - 110.0) < 1e-9


def test_total_notional():
    pf = Portfolio()
    pf.on_fill("BTCUSDT", "BUY", qty=1.0, price=100.0)
    pf.on_fill("ETHUSDT", "BUY", qty=2.0, price=50.0)
    nt = pf.total_notional({"BTCUSDT": 110.0, "ETHUSDT": 60.0})
    assert nt == 110.0 + 120.0
