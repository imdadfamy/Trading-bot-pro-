"""Entry rules shaped by the mechanics of each synthetic-index family, tested against pure chance.

Deriv states that these markets have no order book and that any historical pattern is chance. The point of
this module is therefore not to promise an edge but to test, honestly and cheaply, whether any rule built on a
family's documented mechanics beats random entries with the same trade frequency and side mix.

Safeguards against fooling ourselves:
* every parameter is fixed in advance (no tuning on the data);
* every rule is compared with a Monte Carlo null of random entries placed under the same cost model;
* the chronological test period is reported next to the full-sample figure;
* with several rules tested together the significance threshold is divided by their number (Bonferroni).
Research only: nothing here produces an order.
"""
from __future__ import annotations

import random
from statistics import median, pstdev

from .backtest import BacktestConfig, run_rule, sma_signal
from .market import Candle

SPIKE_K = 5        # a "spike" bar moves at least 5 times the recent median absolute bar return
SCALE_WINDOW = 100  # bars used to measure the recent normal size of a move
QUIET_BARS = 5
WAIT_BARS = 20
Z_K = 2.0
Z_WINDOW = 50


def _scale(closes: list[float], end: int, window: int) -> float:
    """Median absolute one-bar return over the ``window`` bars before position ``end`` (exclusive)."""
    start = max(1, end - window)
    moves = [abs(closes[j] / closes[j - 1] - 1) for j in range(start, end) if closes[j - 1] > 0]
    return median(moves) if moves else 0.0


def _last_return(closes: list[float]) -> float:
    return closes[-1] / closes[-2] - 1 if len(closes) >= 2 and closes[-2] > 0 else 0.0


def large_move_rule(direction: str):
    """``fade``: trade against a spike bar; ``follow``: trade with it."""
    def signal(closes, _candles):
        scale = _scale(closes, len(closes) - 1, SCALE_WINDOW)
        move = _last_return(closes)
        if scale <= 0 or abs(move) < SPIKE_K * scale:
            return None
        up = move > 0
        return ("SELL" if up else "BUY") if direction == "fade" else ("BUY" if up else "SELL")
    return signal


def _spike_in_last(closes, bars: int) -> bool:
    scale = _scale(closes, len(closes) - bars, SCALE_WINDOW)
    if scale <= 0:
        return True  # unknown scale: treat as unsafe, take no trade
    return any(abs(closes[j] / closes[j - 1] - 1) >= SPIKE_K * scale for j in range(len(closes) - bars, len(closes)))


def drift_rider(side: str):
    """Trade in the direction of the slow drift between spikes whenever no spike occurred in the last 5 bars."""
    def signal(closes, _candles):
        return None if _spike_in_last(closes, QUIET_BARS) else side
    return signal


def spike_anticipation(side: str):
    """Trade in the spike direction after 20 bars without a spike (the gambler's fallacy, tested on purpose)."""
    def signal(closes, _candles):
        return None if _spike_in_last(closes, WAIT_BARS) else side
    return signal


def zscore_rule(direction: str):
    """Fade (or follow) a bar that moves at least 2 standard deviations of the last 50 bar returns."""
    def signal(closes, _candles):
        if len(closes) < Z_WINDOW + 2:
            return None
        window = [closes[j] / closes[j - 1] - 1 for j in range(len(closes) - Z_WINDOW - 1, len(closes) - 1)]
        sigma = pstdev(window)
        move = _last_return(closes)
        if sigma <= 0 or abs(move) < Z_K * sigma:
            return None
        up = move > 0
        return ("SELL" if up else "BUY") if direction == "fade" else ("BUY" if up else "SELL")
    return signal


def rules_for(family: str, config: BacktestConfig) -> dict:
    """Rules to test for a family, with their fixed parameters; always includes the moving-average baseline."""
    rules = {"croisement de moyennes 5/20 (référence)": sma_signal(config)}
    if family == "boom":   # spikes up, slow drift down between them
        rules.update({"contre les pics (vente après un pic)": large_move_rule("fade"),
                      "avec les pics (achat après un pic)": large_move_rule("follow"),
                      "dérive entre les pics (vente, calme de 5 bougies)": drift_rider("SELL"),
                      "attente du pic (achat après 20 bougies calmes)": spike_anticipation("BUY")})
    elif family == "crash":  # spikes down, slow drift up between them
        rules.update({"contre les pics (achat après un pic)": large_move_rule("fade"),
                      "avec les pics (vente après un pic)": large_move_rule("follow"),
                      "dérive entre les pics (achat, calme de 5 bougies)": drift_rider("BUY"),
                      "attente du pic (vente après 20 bougies calmes)": spike_anticipation("SELL")})
    elif family == "volatility":  # constant volatility, symmetric returns
        rules.update({"contre les mouvements de 2 écarts-types": zscore_rule("fade"),
                      "avec les mouvements de 2 écarts-types": zscore_rule("follow")})
    else:
        raise ValueError("Family must be boom, crash or volatility")
    return rules


def _split(candles: list[Candle]):
    first, second = int(len(candles) * .6), int(len(candles) * .8)
    return {"entraînement": candles[:first], "validation": candles[first:second], "test": candles[second:]}


def _random_signal(probability: float, buy_share: float, rng: random.Random):
    def signal(_closes, _candles):
        if rng.random() >= probability:
            return None
        return "BUY" if rng.random() < buy_share else "SELL"
    return signal


def _summary(metrics: dict) -> dict:
    return {"trades": metrics["trades"], "profit_factor": metrics["profit_factor"],
            "expectancy_r": metrics["expectancy_r"], "net_pnl": metrics["net_pnl"],
            "win_rate": metrics["win_rate"], "max_drawdown": metrics["max_drawdown"]}


def evaluate(candles: list[Candle], family: str, config: BacktestConfig, *, null_runs: int = 300,
             seed: int = 1, min_trades: int = 30, alpha: float = 0.05) -> dict:
    if null_runs < 50:
        raise ValueError("At least 50 null runs are required for a usable p-value")
    rules = rules_for(family, config)
    threshold = alpha / len(rules)
    bar_seconds = (candles[0].closed_at - candles[0].opened_at).total_seconds()
    results = []
    for name, signal in rules.items():
        full = run_rule(candles, config, signal, name)
        metrics = full["metrics"]
        parts = {part: _summary(run_rule(bars, config, signal, name)["metrics"]) for part, bars in _split(candles).items()}
        row = {"rule": name, **_summary(metrics), "periods": parts, "p_value": None, "null": None,
               "significant": False}
        ledger = full["trades"]
        if metrics["trades"] >= min_trades:
            in_trade = sum((_t(t["closed_at"]) - _t(t["entered_at"])) / bar_seconds for t in ledger)
            free_bars = max(1.0, len(candles) - (config.slow) - in_trade)
            probability = min(1.0, metrics["trades"] / free_bars)
            buy_share = sum(1 for t in ledger if t["action"] == "BUY") / len(ledger)
            rng = random.Random(f"{seed}-{name}")
            nulls = sorted(run_rule(candles, config, _random_signal(probability, buy_share, rng), "null")["metrics"]["expectancy_r"]
                           for _ in range(null_runs))
            beaten_or_tied = sum(1 for value in nulls if value >= metrics["expectancy_r"])
            row["p_value"] = (1 + beaten_or_tied) / (1 + null_runs)
            row["null"] = {"runs": null_runs, "mean_expectancy_r": sum(nulls) / null_runs,
                           "p95_expectancy_r": nulls[int(0.95 * (null_runs - 1))],
                           "random_entry_probability": probability, "buy_share": buy_share}
            test = parts["test"]  # a profit factor is undefined without losing trades: net result decides then
            test_ok = test["net_pnl"] > 0 and (test["profit_factor"] is None or test["profit_factor"] > 1)
            row["significant"] = bool(row["p_value"] <= threshold and metrics["expectancy_r"] > 0 and test_ok)
        results.append(row)
    return {"family": family, "symbol": candles[0].symbol, "bars": len(candles),
            "config": {"stop_distance": config.stop_distance, "reward_multiple": config.reward_multiple,
                       "point_value_per_lot": config.point_value_per_lot, "price_basis": config.price_basis,
                       "stop_fill": config.stop_fill},
            "rules_tested": len(rules), "significance_threshold": threshold, "null_runs": null_runs, "seed": seed,
            "rules": results,
            "reading": "A rule is called significant only if it beats random entries (p below the Bonferroni "
                       "threshold), has a positive expectancy AND a test period above 1. Even then it is a hypothesis "
                       "to confirm on new data, not a validated edge. Parameters were fixed before looking at results."}


def _t(iso: str):
    from datetime import datetime
    return datetime.fromisoformat(iso).timestamp()
