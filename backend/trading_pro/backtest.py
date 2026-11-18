"""Cost-aware research baseline. Never submits orders to any broker."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from .analytics import TradeResult, by_session, performance
from .market import Candle, session_label


@dataclass(frozen=True)
class BacktestConfig:
    fast: int = 5
    slow: int = 20
    stop_distance: float = 3.0
    reward_multiple: float = 2.0
    starting_equity: float = 10_000.0
    risk_fraction: float = .005
    point_value_per_lot: float = 100.0  # illustrative; replace using broker metadata
    commission_per_lot_round_trip: float = 7.0
    slippage_price: float = .1
    max_lot: float = 10.0
    lot_step: float = .01
    min_lot: float = .01
    # "bid": bars are built on the bid price (MetaTrader): a BUY pays the full spread on entry and a SELL's
    # stop and target are tested on ask = bid + spread. "mid": half a spread each way. "auto": detect.
    price_basis: str = "auto"


def load_candles(path: str | Path) -> list[Candle]:
    with open(path, newline="", encoding="utf-8-sig") as stream:
        rows = csv.DictReader(stream)
        required = {"symbol", "opened_at", "closed_at", "open", "high", "low", "close", "bid", "ask", "broker"}
        if not required.issubset(rows.fieldnames or []):
            raise ValueError(f"CSV requires {sorted(required)}")
        candles = [Candle(r["symbol"], datetime.fromisoformat(r["opened_at"]),
                          datetime.fromisoformat(r["closed_at"]),
                          *(float(r[k]) for k in ("open", "high", "low", "close", "bid", "ask")),
                          r["broker"], int(r.get("tick_volume") or 0)) for r in rows]
    if any(a.closed_at > b.opened_at for a, b in zip(candles, candles[1:])):
        raise ValueError("Candles must be chronological, closed and non-overlapping")
    if len({(c.broker, c.symbol, c.opened_at) for c in candles}) != len(candles):
        raise ValueError("Duplicate candle")
    if len({(c.broker, c.symbol) for c in candles}) > 1:
        raise ValueError("Do not mix instruments or brokers")
    return candles


def run_baseline(candles: list[Candle], config: BacktestConfig = BacktestConfig()) -> dict:
    if config.fast < 2 or config.slow <= config.fast or config.stop_distance <= 0 or config.reward_multiple <= 0:
        raise ValueError("Invalid strategy parameters")
    if config.point_value_per_lot <= 0 or config.lot_step <= 0 or config.risk_fraction <= 0 or config.slippage_price < 0:
        raise ValueError("Invalid cost or risk metadata")
    if any(a.closed_at > b.opened_at for a, b in zip(candles, candles[1:])):
        raise ValueError("Overlapping candles")
    if config.price_basis not in {"auto", "mid", "bid"}:
        raise ValueError("price_basis must be auto, mid or bid")
    basis = config.price_basis
    if basis == "auto":
        bid_built = candles and sum(c.bid == c.close for c in candles) >= 0.99 * len(candles)
        basis = "bid" if bid_built else "mid"
    equity = config.starting_equity
    trades: list[TradeResult] = []
    ledger = []
    position = None
    def exit_price_for(bar, position):
        side, entry, stop, target, lots, risk_cash, entered_at = position
        lift = max(0, bar.ask - bar.bid) if basis == "bid" else 0  # a SELL is closed by buying at the ask
        hit_stop = bar.low <= stop if side == "BUY" else bar.high + lift >= stop
        hit_target = bar.high >= target if side == "BUY" else bar.low + lift <= target
        if not (hit_stop or hit_target):
            return None
        exit_price = stop if hit_stop else target  # stop first if path is ambiguous
        if hit_stop:
            exit_price = min(exit_price, bar.open) if side == "BUY" else max(exit_price, bar.open + lift)
        return exit_price + (-config.slippage_price if side == "BUY" else config.slippage_price)

    def close(position, exit_price, bar):
        nonlocal equity
        side, entry, stop, target, lots, risk_cash, entered_at = position
        fees = lots * config.commission_per_lot_round_trip
        pnl = (exit_price-entry) * lots * config.point_value_per_lot * (1 if side == "BUY" else -1) - fees
        equity += pnl
        result = TradeResult(pnl, risk_cash, fees, session_label(entered_at), "SMA baseline 0.1")
        trades.append(result)
        ledger.append({"entered_at": entered_at.isoformat(), "closed_at": bar.closed_at.isoformat(),
                       "action": side, "entry": entry, "exit": exit_price, "lots": lots,
                       "pnl": pnl, "risk_cash": risk_cash, "fees": fees, "session": result.session})

    for i in range(config.slow, len(candles)):
        bar = candles[i]
        if position is not None:
            exit_price = exit_price_for(bar, position)
            if exit_price is not None:
                close(position, exit_price, bar)
                position = None
            continue  # no new entry on same bar, avoid ambiguous execution ordering
        prev = candles[i-1]
        history = [c.close for c in candles[:i]]  # only bars closed before this bar
        current_fast = mean(history[-config.fast:])
        current_slow = mean(history[-config.slow:])
        prior_fast = mean(history[-config.fast-1:-1])
        prior_slow = mean(history[-config.slow-1:-1])
        side = "BUY" if prior_fast <= prior_slow and current_fast > current_slow else (
            "SELL" if prior_fast >= prior_slow and current_fast < current_slow else None)
        if side is None or equity <= 0:
            continue
        spread = max(0, bar.ask - bar.bid)
        if basis == "bid":
            entry = bar.open + (spread + config.slippage_price if side == "BUY" else -config.slippage_price)
        else:
            entry = bar.open + (spread / 2 + config.slippage_price) * (1 if side == "BUY" else -1)
        stop = entry + (-config.stop_distance if side == "BUY" else config.stop_distance)
        target = entry + (config.stop_distance * config.reward_multiple if side == "BUY" else -config.stop_distance * config.reward_multiple)
        risk_budget = equity * config.risk_fraction
        per_lot_risk = ((config.stop_distance + config.slippage_price) * config.point_value_per_lot
                        + config.commission_per_lot_round_trip)
        lots = min(config.max_lot, int((risk_budget / per_lot_risk) / config.lot_step) * config.lot_step)
        if lots < config.min_lot:
            continue
        risk_cash = lots * per_lot_risk
        # Enter on the next bar; do not use future data to select the signal.
        position = (side, entry, stop, target, lots, risk_cash, bar.opened_at)
        # Same-bar stop/target is possible; use worst-case ordering.
        exit_price = exit_price_for(bar, position)
        if exit_price is not None:
            close(position, exit_price, bar)
            position = None
    return {"config": {**config.__dict__, "resolved_price_basis": basis},
            "metrics": performance(trades, config.starting_equity),
            "sessions": by_session(trades, config.starting_equity), "trades": ledger,
            "open_position_at_end": position is not None, "candles": len(candles),
            "warning": "Research baseline; illustrative contract metadata and unverified historical feed"}


def chronological_evaluation(candles: list[Candle], config: BacktestConfig = BacktestConfig()) -> dict:
    """Fixed baseline across chronological splits; no tuning or cross-boundary trades."""
    if len(candles) < 5 * config.slow:
        raise ValueError("Insufficient data for chronological evaluation")
    first = int(len(candles) * .6)
    second = int(len(candles) * .8)
    partitions = {"train": candles[:first], "validation": candles[first:second], "test": candles[second:]}
    if any(len(part) <= config.slow for part in partitions.values()):
        raise ValueError("Each split must have enough closed bars")
    return {name: {"start": part[0].opened_at.isoformat(), "end": part[-1].closed_at.isoformat(),
                   "metrics": run_baseline(part, config)["metrics"], "sample_candles": len(part)}
            for name, part in partitions.items()}
