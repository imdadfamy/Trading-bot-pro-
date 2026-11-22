"""Automatic research pilot: the agents work on every closed bar until the operator switches them off.

Observation mode only. Every cycle records, for several independent "arms" (a baseline rule, the
deterministic graph agent, and model agents with and without skill packs), what each would do and, for
every BUY/SELL, a *shadow trade* that is resolved later from the real bars under the project's cost
model. Nothing here can reach a broker: the only data path is the read-only candle fetch injected by the
caller. Failed model calls are recorded as such and never counted as analyses.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from statistics import median
from uuid import uuid4

from .autopilot_features import atr, features, has_family_word, is_synthetic, skill_pack, spike_stats
from .agents import graph_agent
from .backtest import BacktestConfig, sma_signal
from .core import Action, Limits, Report, Snapshot, utcnow
from .market import Candle, session_label
from .models import Budget, run_model
from .prompts import DIRECTOR_AGENT, build_director_inputs, build_inputs, prompt_tag
from .store import ResearchStore

MODES = ("off", "observe", "demo_auto")
DEMO_AUTO_PHRASE = "ACTIVER LES ORDRES AUTOMATIQUES DEMO"
ARM_NAMES = {"rule:sma_cross", "det:graph", "random:coin", "ai:director", *(f"{v}:{a}" for v in ("plain", "skills", "forced")
                                                           for a in ("graph", "quant", "news", "director"))}
TIMEFRAME_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}
DEFAULT_CONFIG = {
    "symbols": ["Volatility 10 Index", "Boom 500 Index", "Crash 500 Index", "Drift Switch Index 10",
                "Drift Switch Index 20", "Drift Switch Index 30", "XAUUSD"], "timeframe": "M5", "bars": 300,
    # Drift Switch regimes last 10 to 30 minutes on average: M5 bars are too coarse, so they are read on M1 bars.
    "symbol_timeframes": {"Drift Switch Index 10": "M1", "Drift Switch Index 20": "M1", "Drift Switch Index 30": "M1"},
    "model_every_minutes": 30, "horizon_bars": 48, "stop_atr_multiple": 2.0, "reward_multiple": 2.0,
    "skill_pack_size": 3, "max_call_usd": 0.25,
    # Arms whose BUY/SELL becomes a real DEMO order when the mode is "demo_auto" (decisions of the first arm win).
    "execution_arms": ["skills:director"],
    # What to do when an execution arm signals the OPPOSITE direction while a position of this project is open on the
    # instrument: "ignore" (record and show it, the position keeps its stop and target), "close_if_profit" (take the gain)
    # or "close". The opposite position is never opened in the same breath: no blind reversal.
    "opposite_signal_policy": "ignore",
    # Basket mode. simulate: on these instruments every BUY/SELL of an execution arm also opens a SIMULATED basket of
    # identical positions (same stop and target as the single position) that closes as a whole when its gain reaches
    # target_usd; one basket at a time per instrument and arm. enabled: the same as REAL demo orders, in place of the single
    # order on these instruments (off by default). The single-position system is left untouched everywhere else.
    "basket": {"symbols": ["Volatility 10 Index"], "positions": 20, "target_usd": 50.0, "simulate": True, "enabled": False},
}
BASKET_PREFIX = "basket:"
BASKET_ASSUMED_EQUITY = 10000.0  # only used when the account equity has never been read
OPPOSITE_POLICIES = ("ignore", "close_if_profit", "close")
CLOSE_ALL_PHRASE = "FERMER TOUTES LES POSITIONS DEMO"
CONFIG_LIMITS = {"model_every_minutes": (5, 1440), "horizon_bars": (4, 500), "stop_atr_multiple": (0.5, 10),
                 "reward_multiple": (0.5, 10), "skill_pack_size": (0, 8), "max_call_usd": (0.01, 5), "bars": (100, 1000)}
SPIKE_NAMES = ("boom", "crash", "jump", "dex")
EXPOSED_STATUSES = ("open", "resolved")  # statuses that count as a taken shadow trade


# ---------------------------------------------------------------- operational state

def get_mode(store: ResearchStore) -> str:
    mode = store.state_get("autopilot_mode", "off")
    return mode if mode in MODES else "off"


def set_mode(store: ResearchStore, mode: str, *, author: str, execution_available: bool = False) -> dict:
    if mode not in MODES:
        raise ValueError("Mode must be off, observe or demo_auto")
    if not isinstance(author, str) or not 1 <= len(author) <= 100:
        raise ValueError("Operator identity required")
    if mode == "demo_auto":
        if not execution_available:
            raise PermissionError("The MT5 execution bridge is unavailable in this process: demo orders cannot be sent")
        if not get_config(store).get("execution_arms"):
            raise PermissionError("Choose at least one execution arm in the settings first")
    previous = get_mode(store)
    store.state_set("autopilot_mode", mode)
    store.journal.log("autopilot.mode_changed", "global", {"from": previous, "to": mode, "author": author})
    if mode == "demo_auto":  # activating the automatic orders is the deliberate act that lifts the stop on entries
        store.release_killed(author=author, reason="demo_auto activated")
    elif previous == "demo_auto":  # leaving it stops new entries at once; open positions keep their broker-side stops
        store.set_killed()
    return {"mode": mode, "previous": previous}


def get_config(store: ResearchStore) -> dict:
    raw = store.state_get("autopilot_config")
    config = dict(DEFAULT_CONFIG)
    if raw:
        config.update(json.loads(raw))
    return config


def timeframe_for(config: dict, symbol: str) -> str:
    return config.get("symbol_timeframes", {}).get(symbol, config["timeframe"])


def set_config(store: ResearchStore, patch: dict, *, author: str) -> dict:
    config = get_config(store)
    for key, item in patch.items():
        if key not in DEFAULT_CONFIG:
            raise ValueError(f"Unknown setting: {key}")
        if key == "symbols":
            if (not isinstance(item, list) or not 1 <= len(item) <= 12
                    or any(not isinstance(s, str) or not 1 <= len(s) <= 60 for s in item)):
                raise ValueError("symbols must be 1 to 12 instrument names")
        elif key == "opposite_signal_policy":
            if item not in OPPOSITE_POLICIES:
                raise ValueError("opposite_signal_policy must be one of " + ", ".join(OPPOSITE_POLICIES))
        elif key == "execution_arms":
            if not isinstance(item, list) or len(item) > 6 or any(a not in ARM_NAMES for a in item):
                raise ValueError("execution_arms must be a list of known arms, for example skills:director")
        elif key == "basket":
            if (not isinstance(item, dict) or set(item) - set(DEFAULT_CONFIG["basket"])
                    or not isinstance(item.get("symbols", []), list) or len(item.get("symbols", [])) > 12
                    or any(not isinstance(s, str) or not 1 <= len(s) <= 60 for s in item.get("symbols", []))
                    or not isinstance(item.get("simulate", True), bool) or not isinstance(item.get("enabled", False), bool)):
                raise ValueError("basket must hold symbols (list), positions, target_usd, simulate and enabled (true/false)")
            for sub, (low, high) in {"positions": (2, 50), "target_usd": (1, 100000)}.items():
                if sub in item and (isinstance(item[sub], bool) or not isinstance(item[sub], (int, float)) or not low <= item[sub] <= high):
                    raise ValueError(f"basket.{sub} must be between {low} and {high}")
            item = {**config.get("basket", DEFAULT_CONFIG["basket"]), **item}
        elif key == "timeframe":
            if item not in TIMEFRAME_SECONDS:
                raise ValueError("timeframe must be one of " + ", ".join(TIMEFRAME_SECONDS))
        elif key == "symbol_timeframes":
            if (not isinstance(item, dict) or len(item) > 12
                    or any(not isinstance(s, str) or tf not in TIMEFRAME_SECONDS for s, tf in item.items())):
                raise ValueError("symbol_timeframes must map instrument names to " + ", ".join(TIMEFRAME_SECONDS))
        else:
            low, high = CONFIG_LIMITS[key]
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not low <= item <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
        config[key] = item
    store.state_set("autopilot_config", json.dumps(config))
    store.journal.log("autopilot.config_changed", "global", {"patch": patch, "author": author})
    return config


# ---------------------------------------------------------------- director and shadow trades

def consensus(votes: dict[str, Action]) -> tuple[Action, str]:
    """Two independent agreeing voters and nobody opposed; the risk agent never votes on direction."""
    buys = [a for a, v in votes.items() if v == Action.BUY]
    sells = [a for a, v in votes.items() if v == Action.SELL]
    if len(votes) < 2:
        return Action.WAIT, "fewer than two answering analysts"
    if len(buys) >= 2 and not sells:
        return Action.BUY, "at least two analysts buy and none sells: " + ", ".join(sorted(buys))
    if len(sells) >= 2 and not buys:
        return Action.SELL, "at least two analysts sell and none buys: " + ", ".join(sorted(sells))
    if buys and sells:
        return Action.WAIT, "analysts disagree"
    return Action.WAIT, "no pair of analysts agrees on a direction"


COST_FLOOR_FACTOR = 10.0   # a stop is never tighter than ten spreads: the spread then costs at most 0.1 R
SPIKE_FLOOR_PCT = 0.002    # Boom/Crash default (measured p90 spike on Boom/Crash 1000 M1, 19 Nov 2026): 0.2% of price


def trade_plan(candles: list[Candle], config: dict) -> dict | None:
    """Stop and target of a decision, adapted to the instrument rather than refused.

    The stop is the largest of: the volatility stop (ATR), ten spreads (cost cap) and, for Boom/Crash style indices,
    the 90th-percentile spike (a tighter stop is simply jumped). The volume is then sized from the money at risk, so
    an instrument whose points are cheap (a synthetic index: one lot earns one dollar per price unit; gold: a hundred)
    gets a bigger or smaller lot, never an automatic refusal for its scale.
    """
    value = atr(candles)
    if not value or value <= 0:
        return None
    last = candles[-1]
    floors = {"atr": config["stop_atr_multiple"] * value}
    spread = max(last.ask - last.bid, 0.0)
    if spread > 0:
        floors["spread"] = COST_FLOOR_FACTOR * spread
    if has_family_word(last.symbol, ("boom", "crash")):
        spikes = spike_stats(candles)
        if spikes and spikes["count"] >= 10 and spikes["p90_move_pct"]:
            floors["spike"] = spikes["p90_move_pct"] / 100 * last.close
        else:
            floors["spike"] = SPIKE_FLOOR_PCT * last.close  # too few spikes in the window to measure: the default
    basis = max(floors, key=floors.get)
    return {"stop_distance": round(floors[basis], 8), "reward_multiple": config["reward_multiple"],
            "horizon_bars": int(config["horizon_bars"]), "atr_14": round(value, 8), "stop_basis": basis}


def resolve_trade(side: str, plan: dict, bars: list[Candle], *, spike_gap: bool = False,
                  spike_range: float = float("inf")) -> dict | None:
    """Walk the real bars after a decision. Bars are bid-built: a BUY pays the spread on entry and a SELL is
    stopped/closed on ask = bid + spread. Stop first when a bar touches both. None = not enough bars yet."""
    if not bars:
        return None
    distance = plan["stop_distance"]
    target_distance = distance * plan["reward_multiple"]
    first = bars[0]
    entry = first.open + (max(first.ask - first.bid, 0) if side == "BUY" else 0)
    stop = entry - distance if side == "BUY" else entry + distance
    target = entry + target_distance if side == "BUY" else entry - target_distance
    mfe = mae = 0.0
    horizon = plan["horizon_bars"]
    for held, bar in enumerate(bars[:horizon], start=1):
        lift = max(bar.ask - bar.bid, 0) if side == "SELL" else 0
        favourable = (bar.high - entry) if side == "BUY" else (entry - (bar.low + lift))
        adverse = (entry - bar.low) if side == "BUY" else ((bar.high + lift) - entry)
        hit_stop = bar.low <= stop if side == "BUY" else bar.high + lift >= stop
        hit_target = bar.high >= target if side == "BUY" else bar.low + lift <= target
        mfe = max(mfe, favourable / distance)
        mae = max(mae, adverse / distance)
        if hit_stop or hit_target:
            exit_price = stop if hit_stop else target
            if hit_stop:
                exit_price = min(exit_price, bar.open) if side == "BUY" else max(exit_price, bar.open + lift)
                if spike_gap and bar.high - bar.low >= spike_range:
                    exit_price = min(exit_price, bar.low) if side == "BUY" else max(exit_price, bar.high + lift)
            result = "stop" if hit_stop else "target"
            return _outcome(side, entry, exit_price, distance, result, held, mfe, mae)
    if len(bars) >= horizon:
        last = bars[horizon - 1]
        exit_price = last.close + (max(last.ask - last.bid, 0) if side == "SELL" else 0)
        return _outcome(side, entry, exit_price, distance, "timeout", horizon, mfe, mae)
    return None


def score_direction(side: str, unit: float, bars: list[Candle], horizon: int) -> float | None:
    """Fixed-horizon quality of a direction: the signed move after ``horizon`` bars, in stop distances, after the spread.

    Unlike a shadow trade it has no stop or target and no position lock, so every BUY/SELL answer of a scored
    cycle yields one observation (horizons equal the model cadence, so observations do not overlap). None = not yet.
    """
    if len(bars) < horizon or horizon < 1 or unit <= 0:
        return None
    first, last = bars[0], bars[horizon - 1]
    entry = first.open + (max(first.ask - first.bid, 0) if side == "BUY" else 0)
    exit_price = last.close + (max(last.ask - last.bid, 0) if side == "SELL" else 0)
    move = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    return round(move / unit, 4)


def _outcome(side, entry, exit_price, distance, result, held, mfe, mae):
    move = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    return {"result": result, "r_multiple": round(move / distance, 4), "bars_held": held,
            "mfe_r": round(mfe, 4), "mae_r": round(mae, 4), "entry": entry, "exit_price": exit_price}


# ---------------------------------------------------------------- the pilot

@dataclass
class ModelSetup:
    provider: object
    models: dict
    budget: Budget


class Autopilot:
    def __init__(self, store: ResearchStore, *, fetch, model_setup=None,
                 clock=utcnow, calendar_loader=None, skills_root=None, executor=None, limits_provider=None,
                 risk_provider=None):
        self.store = store
        self.fetch = fetch
        self.executor = executor
        self._last_account = None
        self._last_positions = None
        self.limits_provider = limits_provider or Limits
        self.risk_provider = risk_provider or (lambda: {"fixed_lot": None, "commission_per_lot": 0.0, "slippage_ticks": 0.0})
        self.offset_hours = 0.0
        store.state_set("autopilot_exec_ready", "true" if executor is not None else "false")
        self.model_setup = model_setup
        self.clock = clock
        self.skills_root = skills_root
        if calendar_loader is None:
            from . import us_events

            def calendar_loader():
                try:
                    return us_events.load()
                except FileNotFoundError:
                    return None
        self.calendar_loader = calendar_loader
        self._lock = threading.Lock()

    # -- helpers
    def _beat(self, **changes) -> dict:
        raw = self.store.state_get("autopilot_heartbeat")
        beat = json.loads(raw) if raw else {"cycles": 0, "errors": 0, "last_error": None, "last_cycle": {}}
        beat.update(changes)
        beat["at"] = self.clock().isoformat()
        self.store.state_set("autopilot_heartbeat", json.dumps(beat, default=str))
        return beat

    def heartbeat(self) -> dict:
        raw = self.store.state_get("autopilot_heartbeat")
        return json.loads(raw) if raw else {}

    def _record(self, cycle_id, symbol, at, arm, action, status, detail) -> str:
        decision_id = str(uuid4())
        with self.store.journal.connect() as db:
            db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?)",
                       (decision_id, cycle_id, symbol, at.isoformat(), session_label(at), arm, action, status,
                        json.dumps(detail, default=str, ensure_ascii=False)))
        self.store.journal.log("autopilot.decision", decision_id,
                               {"cycle_id": cycle_id, "symbol": symbol, "arm": arm, "action": action, "status": status})
        return decision_id

    # -- basket twin (simulation): the same decision, traded as a basket that closes as a whole on a money target
    def _basket_risk_money(self) -> tuple[float, bool]:
        account = json.loads(self.store.state_get("autopilot_account") or "null") or {}
        equity = float(account.get("equity") or account.get("balance") or 0)
        assumed = equity <= 0
        if assumed:
            equity = BASKET_ASSUMED_EQUITY
        return equity * float(self.limits_provider().risk_per_trade), assumed

    def _basket_twin(self, cycle_id, symbol, at, arm, action, plan, config, origin_id, origin_status) -> None:
        basket = config.get("basket") or {}
        if not basket.get("simulate") or symbol not in basket.get("symbols", []) or arm not in config.get("execution_arms", []):
            return
        risk_money, assumed = self._basket_risk_money()
        target_usd = float(basket["target_usd"])
        # The basket's total risk is the single position's risk (0.5% of equity by default), so +target_usd is
        # target_usd / risk_money times the stop distance; the positions' own target (reward_multiple) still applies.
        target_r = target_usd / risk_money if risk_money > 0 else plan["reward_multiple"]
        detail = {"variant": "basket",
                  "rationale": f"basket of {basket['positions']} identical positions, closed together at +{target_usd:g} USD (simulation)",
                  "twin_of": origin_id if origin_status == "open" else None,
                  "basket": {"positions": basket["positions"], "target_usd": target_usd, "risk_money": round(risk_money, 2),
                             "target_r": round(target_r, 4), "equity_assumed": assumed}}
        twin_arm = BASKET_PREFIX + arm
        if self._has_open(symbol, twin_arm):  # one basket at a time: the next one starts only once this one is closed
            status = "skipped_open"
        else:
            status = "open"
            detail["plan"] = {**plan, "reward_multiple": round(min(plan["reward_multiple"], target_r), 6)}
        self._record(cycle_id, symbol, at, twin_arm, action, status, detail)

    def _has_open(self, symbol, arm) -> bool:
        with self.store.journal.connect() as db:
            return db.execute("SELECT 1 FROM decisions WHERE symbol=? AND arm=? AND status='open' LIMIT 1",
                              (symbol, arm)).fetchone() is not None

    def _spike_settings(self, symbol, candles):
        spike = has_family_word(symbol, SPIKE_NAMES)
        rng = 5.0 * median(c.high - c.low for c in candles) if spike and candles else float("inf")
        return spike, rng

    # -- resolution of shadow trades
    def resolve_open(self, symbol: str, candles: list[Candle]) -> int:
        resolved = 0
        spike, spike_range = self._spike_settings(symbol, candles)
        step = TIMEFRAME_SECONDS[timeframe_for(get_config(self.store), symbol)]
        with self.store.journal.connect() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT decision_id,at,action,detail,arm FROM decisions WHERE symbol=? AND status='open'", (symbol,))]
        for row in rows:
            detail = json.loads(row["detail"])
            decided = datetime.fromisoformat(row["at"])
            bars = [c for c in candles if c.opened_at >= decided]
            if bars and (bars[0].opened_at - decided).total_seconds() > 2 * step:
                # The entry bar is missing (market break, restart after a long stop, bar left the window).
                with self.store.journal.connect() as db:
                    db.execute("UPDATE decisions SET status='expired' WHERE decision_id=?", (row["decision_id"],))
                self.store.journal.log("autopilot.expired", row["decision_id"], {"arm": row["arm"], "symbol": symbol})
                continue
            outcome = resolve_trade(row["action"], detail["plan"], bars, spike_gap=spike, spike_range=spike_range)
            if outcome is None:
                continue
            with self.store.journal.connect() as db:
                db.execute("INSERT OR IGNORE INTO decision_outcomes VALUES(?,?,?,?,?,?,?,?,?)",
                           (row["decision_id"], self.clock().isoformat(), outcome["result"], outcome["r_multiple"],
                            outcome["bars_held"], outcome["mfe_r"], outcome["mae_r"], outcome["entry"],
                            outcome["exit_price"]))
                db.execute("UPDATE decisions SET status='resolved' WHERE decision_id=?", (row["decision_id"],))
            self.store.journal.log("autopilot.outcome", row["decision_id"],
                                   {"arm": row["arm"], "symbol": symbol, "result": outcome["result"],
                                    "r_multiple": outcome["r_multiple"]})
            resolved += 1
        return resolved

    def resolve_directions(self, symbol: str, candles: list[Candle]) -> int:
        step = TIMEFRAME_SECONDS[timeframe_for(get_config(self.store), symbol)]
        with self.store.journal.connect() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT decision_id,at,action,horizon_bars,unit FROM direction_pending WHERE symbol=?", (symbol,))]
        done = 0
        for row in rows:
            decided = datetime.fromisoformat(row["at"])
            bars = [c for c in candles if c.opened_at >= decided]
            if bars and (bars[0].opened_at - decided).total_seconds() > 2 * step:
                with self.store.journal.connect() as db:
                    db.execute("DELETE FROM direction_pending WHERE decision_id=?", (row["decision_id"],))
                self.store.journal.log("autopilot.expired", row["decision_id"], {"symbol": symbol, "kind": "direction"})
                continue
            value = score_direction(row["action"], row["unit"], bars, row["horizon_bars"])
            if value is None:
                continue
            with self.store.journal.connect() as db:
                db.execute("INSERT OR IGNORE INTO direction_scores VALUES(?,?,?,?)",
                           (row["decision_id"], self.clock().isoformat(), row["horizon_bars"], value))
                db.execute("DELETE FROM direction_pending WHERE decision_id=?", (row["decision_id"],))
            self.store.journal.log("autopilot.scored", row["decision_id"], {"symbol": symbol, "score": value})
            done += 1
        return done

    # -- one cycle for one instrument
    def run_symbol(self, symbol: str) -> dict:
        with self._lock:
            return self._run_symbol(symbol)

    def _run_symbol(self, symbol: str) -> dict:
        config = get_config(self.store)
        timeframe = timeframe_for(config, symbol)
        step = TIMEFRAME_SECONDS[timeframe]
        now = self.clock()
        try:
            candles, meta = self.fetch(symbol, timeframe, int(config["bars"]))
        except Exception as exc:  # noqa: BLE001 - the loop must survive any data problem
            if "No live tick" in str(exc):  # a closed market (gold at night or on the weekend) is not an error
                return {"symbol": symbol, "status": "stale", "message": "marché fermé : aucune cotation"}
            self.store.journal.log("autopilot.data_error", symbol, {"error": type(exc).__name__, "message": str(exc)[:200]})
            return {"symbol": symbol, "status": "data_error", "message": str(exc)[:200]}
        if len(candles) < 40:
            return {"symbol": symbol, "status": "data_error", "message": "fewer than 40 closed candles"}
        last = candles[-1]
        if isinstance(meta, dict) and "server_offset_hours" in meta:
            self.offset_hours = float(meta["server_offset_hours"])
        if (now - last.closed_at).total_seconds() > 3 * step:
            return {"symbol": symbol, "status": "stale", "last_close": last.closed_at.isoformat()}
        last_bar = self.store.state_get(f"autopilot_last_bar:{symbol}")
        if last_bar and last.closed_at <= datetime.fromisoformat(last_bar):
            self.resolve_open(symbol, candles)
            self.resolve_directions(symbol, candles)
            return {"symbol": symbol, "status": "no_new_bar"}
        floor = datetime.fromisoformat(last_bar) if last_bar else datetime.min.replace(tzinfo=timezone.utc)
        for candle in candles:
            if candle.closed_at > floor:
                self.store.candle(candle)
        resolved = self.resolve_open(symbol, candles)
        self.resolve_directions(symbol, candles)

        cycle_id = str(uuid4())
        self.store.snapshot(Snapshot(cycle_id, symbol, last.bid, last.ask, last.closed_at, last.broker))
        baselines = {}
        synthetic = is_synthetic(symbol)
        halt = ""
        if not synthetic:
            calendar = self.calendar_loader()
            if calendar is not None:
                try:
                    halt = calendar.halt_reason(last.closed_at) or ""
                except ValueError:
                    halt = "US announcement calendar invalid"
        plan = trade_plan(candles, config)
        closes = [c.close for c in candles]
        # A "scored cycle" happens once per model cadence: every arm's BUY/SELL of that cycle also gets a fixed-horizon
        # direction score, so far more observations accumulate than the one-position-per-arm shadow trades allow.
        score_key = f"autopilot_last_score:{symbol}"
        previous = self.store.state_get(score_key)
        cadence = timedelta(minutes=config["model_every_minutes"])
        scored = (not halt) and (not previous or (now - datetime.fromisoformat(previous)) >= cadence)
        if scored:
            self.store.state_set(score_key, now.isoformat())
        horizon = max(2, round(config["model_every_minutes"] * 60 / step))
        summary = {"cycle_id": cycle_id, "symbol": symbol, "bar_close": last.closed_at.isoformat(),
                   "session": session_label(last.closed_at), "halt": halt, "resolved": resolved, "arms": {}}
        if halt:
            self.store.journal.log("announcement.blackout", cycle_id, {"reason": halt})
        else:
            def propose(arm, action, detail):
                action = Action(action) if not isinstance(action, Action) else action
                if action == Action.WAIT:
                    status = "wait"
                elif plan is None:
                    status = "skipped_no_atr"
                elif self._has_open(symbol, arm):
                    status = "skipped_open"
                else:
                    status, detail = "open", {**detail, "plan": plan}
                decision_id = self._record(cycle_id, symbol, last.closed_at, arm, action.value, status, detail)
                summary["arms"][arm] = f"{action.value}/{status}"
                if action != Action.WAIT and plan is not None:
                    self._basket_twin(cycle_id, symbol, last.closed_at, arm, action.value, plan, config, decision_id, status)
                if scored and action != Action.WAIT and plan is not None:
                    with self.store.journal.connect() as db:
                        db.execute("INSERT OR IGNORE INTO direction_pending VALUES(?,?,?,?,?,?)",
                                   (decision_id, symbol, last.closed_at.isoformat(), action.value, horizon,
                                    plan["stop_distance"]))

            cross = sma_signal(BacktestConfig())(closes, candles)
            propose("rule:sma_cross", cross or "WAIT", {"rationale": "SMA 5/20 crossover on closed bars"})
            graph = graph_agent(closes)
            propose("det:graph", graph.action, {"rationale": graph.rationale})
            baselines.update({"rule_sma_cross": cross or "WAIT", "det_graph": graph.action.value})
            coin = "BUY" if int(sha256(cycle_id.encode()).hexdigest(), 16) % 2 else "SELL"
            propose("random:coin", coin, {"rationale": "seeded coin flip: the chance reference for the forced-direction arms"})
            self._model_arms(symbol, cycle_id, last, candles, config, propose, summary, scored, plan, baselines)
            if get_mode(self.store) == "demo_auto" and self.executor is not None and plan is not None:
                self._execute_arms(symbol, cycle_id, plan, step, config, summary, now)
        self.store.state_set(f"autopilot_last_bar:{symbol}", last.closed_at.isoformat())
        self.store.journal.log("autopilot.cycle", cycle_id, summary)
        beat = self.heartbeat()
        self._beat(cycles=beat.get("cycles", 0) + 1, last_cycle={**beat.get("last_cycle", {}), symbol: summary})
        return {"symbol": symbol, "status": "halted" if halt else "ok", **summary}

    # -- the AI director: reads every report of the consultation (and a short history where it means something)
    PERSISTENT = ("drift",)

    def _history(self, symbol: str, limit: int = 4, exclude_cycle: str | None = None) -> list[dict]:
        with self.store.journal.connect() as db:
            cycles = [r["cycle_id"] for r in db.execute(
                "SELECT DISTINCT cycle_id FROM decisions WHERE symbol=? AND arm='skills:director' AND cycle_id<>? "
                "ORDER BY at DESC LIMIT ?", (symbol, exclude_cycle or "", limit))]
            rows = []
            for cycle in cycles:
                votes = {("ai_director" if r["arm"] == "ai:director" else r["arm"].split(":")[1]): r["action"] for r in db.execute(
                    "SELECT arm, action FROM decisions WHERE cycle_id=? AND arm IN "
                    "('skills:graph','skills:quant','skills:news','skills:director','ai:director')", (cycle,))}
                at = db.execute("SELECT at FROM decisions WHERE cycle_id=? LIMIT 1", (cycle,)).fetchone()["at"]
                snap = db.execute("SELECT payload FROM snapshots WHERE cycle_id=?", (cycle,)).fetchone()
                price = json.loads(snap["payload"]).get("bid") if snap else None
                rows.append({"at": at, "votes": votes, "price": price})
        return rows

    def _ai_director(self, setup, symbol, cycle_id, last, plan, numeric, upcoming, skills_reports, baselines, config,
                     propose, summary, budget):
        arm = f"ai:{DIRECTOR_AGENT}"
        detail = {"variant": "director", "prompt": prompt_tag(DIRECTOR_AGENT), "relied_on": sorted(skills_reports)}
        if len(skills_reports) < 2 or plan is None:
            self._record(cycle_id, symbol, last.closed_at, arm, "WAIT", "model_failed",
                         {**detail, "rationale": "fewer than two analyst answers to reconcile"})
            summary["arms"][arm] = "WAIT/model_failed"
            return
        persistent = (not is_synthetic(symbol)) or has_family_word(symbol, self.PERSISTENT)
        keep = ("atr_14", "atr_percentile", "structure", "rsi_14", "drift", "drift_short", "spikes", "setup_ma_rsi",
                "spread_to_atr", "session")
        indicators = {k: numeric.get(k) for k in keep} if numeric.get("available") else {}
        inputs = build_director_inputs(
            cycle_id=cycle_id, symbol=symbol, observed_at=last.closed_at, reports=skills_reports, baselines=baselines,
            plan=plan, spread=max(last.ask - last.bid, 0.0), indicators=indicators, announcements=upcoming,
            history=self._history(symbol, exclude_cycle=cycle_id) if persistent else None)
        pack = skill_pack(DIRECTOR_AGENT, symbol, cycle_id, size=int(config["skill_pack_size"]),
                          **({"root": self.skills_root} if self.skills_root else {}))
        family = ("Instrument family: Deriv synthetic index (simulated, 24/7, no news channel)." if is_synthetic(symbol)
                  else "Instrument family: gold against the US dollar (XAUUSD).")
        inputs["method_notes"] = family + ("\n\n" + pack["text"] if pack["text"] else "")
        estimate = setup.provider.estimate_cost
        model = setup.models.get(DIRECTOR_AGENT) or setup.models["graph"]
        report = run_model(self.store, setup.provider, agent=DIRECTOR_AGENT, model=model, snapshot=inputs,
                           budget=budget, projected_cost_usd=estimate(DIRECTOR_AGENT, inputs))
        detail.update(rationale=report.rationale[:600], evidence=list(report.evidence)[:8], score=report.score,
                      model=model, skills=pack["skills"], skills_sha256=pack["sha256"], history_used=persistent)
        if report.rationale in FAILURE_RATIONALES:
            self._record(cycle_id, symbol, last.closed_at, arm, "WAIT", "model_failed", detail)
            summary["arms"][arm] = "WAIT/model_failed"
            return
        propose(arm, report.action, detail)

    # -- automatic demo orders
    def _execute_arms(self, symbol, cycle_id, plan, step, config, summary, now) -> None:
        """Send the decision of the first execution arm that opened a BUY/SELL this cycle. One order per symbol."""
        with self.store.journal.connect() as db:
            rows = {r["arm"]: dict(r) for r in db.execute(
                "SELECT decision_id, arm, action, detail FROM decisions WHERE cycle_id=? "
                "AND status IN ('open','skipped_open')", (cycle_id,))}
        here = [o for o in self.store.open_orders() if o["symbol"] == symbol]
        if here:  # a real position of the project is open on this instrument: it lives on its broker-side stop
            self._opposite_signal(symbol, here[0], rows, config, summary, now)
            return
        if self.store.killed():
            summary["orders"] = {"all": "stopped"}  # the emergency stop is active: analysis goes on, no attempt is made
            return
        for arm in config.get("execution_arms", []):
            row = rows.get(arm)
            if row is None or row["action"] not in ("BUY", "SELL"):
                continue
            halt = None
            if not is_synthetic(symbol):
                calendar = self.calendar_loader()
                try:
                    halt = (calendar.halt_reason(now, strict=True) if calendar is not None
                            else "US announcement calendar missing")
                except ValueError:
                    halt = "US announcement calendar invalid"
            basket = config.get("basket") or {}
            as_basket = bool(basket.get("enabled")) and symbol in basket.get("symbols", [])
            try:
                options = dict(decision_id=row["decision_id"], symbol=symbol, side=row["action"], arm=arm,
                               plan={**plan, "max_age_seconds": int(plan["horizon_bars"] * step)}, limits=self.limits_provider(),
                               risk=self.risk_provider(), ai_spend=self.store.costs()["total_usd"], offset_hours=self.offset_hours,
                               now=now, halt=halt, rationale=json.loads(row["detail"]).get("rationale", ""))
                if as_basket:  # a basket of identical positions in place of the single order, all or nothing
                    report = self.executor.send_basket(self.store, positions=int(basket["positions"]),
                                                       target_usd=float(basket["target_usd"]), **options)
                else:
                    report = self.executor.send(self.store, **options)
            except Exception as exc:  # noqa: BLE001 - an execution problem must never stop the analysis
                self.store.journal.log("autopilot.error", symbol, {"error": type(exc).__name__, "message": str(exc)[:200]})
                summary.setdefault("orders", {})[arm] = f"error:{type(exc).__name__}"
                return
            summary.setdefault("orders", {})[arm] = report["state"] + (f":{report['code']}" if report.get("code") else "")
            if report["state"] != "refused":
                return

    def _members_of(self, order) -> list[dict]:
        basket_id = order.get("basket_id")
        if not basket_id:
            return [order]
        return [o for o in self.store.open_orders() if o.get("basket_id") == basket_id]

    def check_baskets(self, positions) -> list[str]:
        """Close a basket as a whole when the money it made (closed members + floating members) reaches its target."""
        if self.executor is None or not positions:
            return []
        groups: dict[str, list[dict]] = {}
        for order in self.store.open_orders():
            if order.get("basket_id"):
                groups.setdefault(order["basket_id"], []).append(order)
        live = {p.get("ticket"): float(p.get("profit") or 0.0) for p in positions}
        closed = []
        for basket_id, members in groups.items():
            meta = json.loads(self.store.state_get(f"basket:{basket_id}") or "null") or {}
            target = float(meta.get("target_usd") or 0)
            if target <= 0:
                continue
            total = self.store.basket_realised(basket_id) + sum(live.get(m["position_ticket"], 0.0) for m in members)
            if total < target:
                continue
            with self._lock:
                result = self.executor.close_tickets(self.store, [m["position_ticket"] for m in members],
                                                     reason=f"basket target {target:g}")
            self.store.journal.log("autopilot.basket_target", basket_id, {"symbol": meta.get("symbol"), "total": round(total, 2),
                                                                         "target": target, "members": len(members),
                                                                         "close": result.get("status")})
            if result.get("status") == "sent":
                closed.append(basket_id)
        return closed

    def _live_profit(self, ticket) -> float | None:
        snap = json.loads(self.store.state_get("autopilot_positions") or "null") or {}
        for p in snap.get("positions", []):
            if p.get("ticket") == ticket:
                return p.get("profit")
        return None

    def _opposite_signal(self, symbol, order, rows, config, summary, now) -> None:
        """An execution arm says the opposite of the open position. Record it, show it, apply the chosen policy.

        The position is never reversed in the same breath (no blind reversal); the opposite order, if the signal
        persists, goes through every safeguard like any other once the position is gone.
        """
        for arm in config.get("execution_arms", []):
            row = rows.get(arm)
            if row is None or row["action"] not in ("BUY", "SELL") or row["action"] == order["side"]:
                continue
            key = f"autopilot_conflict:{symbol}"
            previous = json.loads(self.store.state_get(key) or "null") or {}
            members = self._members_of(order)
            lives = [self._live_profit(m["position_ticket"]) for m in members]
            profit = None if any(v is None for v in lives) else round(sum(lives), 2)
            conflict = {"at": now.isoformat(), "arm": arm, "signal": row["action"], "position_side": order["side"],
                        "ticket": order["position_ticket"], "decision_id": row["decision_id"], "profit": profit,
                        "policy": config.get("opposite_signal_policy", "ignore"), "action": "ignored"}
            policy = conflict["policy"]
            if (policy == "close" or (policy == "close_if_profit" and profit is not None and profit > 0)) \
                    and self.executor is not None and order["position_ticket"]:
                try:  # called from inside run_symbol, which already holds the pilot's lock (one MT5 user at a time)
                    reason = f"{policy}: {arm} says {row['action']}"
                    if order.get("basket_id"):  # a basket is closed as a whole
                        result = self.executor.close_tickets(self.store, [m["position_ticket"] for m in members], reason=reason)
                    else:
                        result = self.executor.close_position_by_ticket(self.store, int(order["position_ticket"]), reason=reason)
                    conflict["action"] = "closed" if result.get("status") == "sent" else f"close_{result.get('status')}"
                except Exception as exc:  # noqa: BLE001
                    conflict["action"] = f"close_error:{type(exc).__name__}"
            self.store.state_set(key, json.dumps(conflict))
            if previous.get("decision_id") != row["decision_id"]:
                self.store.journal.log("autopilot.opposite_signal", row["decision_id"],
                                       {"symbol": symbol, "arm": arm, "signal": row["action"], "position": order["side"],
                                        "profit": profit, "policy": policy, "action": conflict["action"]})
            summary["conflict"] = f"{row['action']} vs {order['side']}: {conflict['action']}"
            return

    def refresh_positions(self, force: bool = False) -> None:
        """Live view of the open positions for the interface (every ten seconds while any is open)."""
        if self.executor is None:
            return
        now = self.clock()
        if not self.store.open_orders():
            if self.store.state_get("autopilot_positions"):
                self.store.state_set("autopilot_positions", json.dumps({"at": now.isoformat(), "positions": []}))
            return None
        if not force and self._last_positions is not None and (now - self._last_positions).total_seconds() < 10:
            return None
        self._last_positions = now
        with self._lock:
            try:
                positions = self.executor.positions_snapshot(self.offset_hours)
            except Exception:  # noqa: BLE001 - the interface keeps its last values
                return None
        self.store.state_set("autopilot_positions", json.dumps({"at": now.isoformat(), "positions": positions}))
        return positions

    def handle_close_request(self):
        """Execute a 'close everything' request made from the interface (always in this thread: one MT5 user at a time)."""
        if self.executor is None:
            return None
        raw = self.store.state_get("autopilot_close_request")
        if not raw:
            return None
        self.store.state_set("autopilot_close_request", "")
        request = json.loads(raw)
        with self._lock:
            result = self.executor.close_all(self.store, author=request.get("author", "operator"), now=self.clock())
        self.refresh_positions(force=True)
        return result

    def refresh_account(self) -> None:
        """Keep the account's capital and equity fresh for the dashboard (every five minutes, any mode)."""
        if self.executor is None:
            return
        now = self.clock()
        if self._last_account is not None and (now - self._last_account).total_seconds() < 300:
            return
        self._last_account = now
        with self._lock:
            try:
                summary = self.executor.account_summary()
            except Exception:  # noqa: BLE001 - the dashboard simply keeps its last values
                return
        self.store.state_set("autopilot_account", json.dumps({**summary, "at": now.isoformat()}))

    def reconcile_orders(self) -> dict:
        """Follow open orders (also after the mode was switched off: positions still need their follow-up)."""
        if self.executor is None or not self.store.open_orders():
            return {"checked": 0}
        with self._lock:
            return self.executor.reconcile(self.store, now=self.clock(), offset_hours=self.offset_hours)

    # -- model arms
    def _model_arms(self, symbol, cycle_id, last, candles, config, propose, summary, scored, plan=None, baselines=None):
        setup = self.model_setup() if callable(self.model_setup) else self.model_setup
        if isinstance(setup, str):
            summary["models"] = setup
            return
        if setup is None:
            summary["models"] = "not configured"
            return
        if not scored:
            summary["models"] = "not due"
            return
        voters = ["graph", "quant"] + ([] if is_synthetic(symbol) else ["news"])
        missing = [a for a in voters if not setup.models.get(a)]
        if missing:
            summary["models"] = "model not configured for " + ", ".join(missing)
            return
        closes = [c.close for c in candles]
        headlines = [{"headline": e["headline"], "source": e["source"], "status": e["status"],
                      "relevance": e.get("relevance", "unclassified"), "published_at": e["published_at"]}
                     for e in self.store.news_as_of(last.closed_at)
                     if e.get("relevance") in ("medium", "high")][-10:]
        numeric = features(candles)
        upcoming = []
        if not is_synthetic(symbol):
            calendar = self.calendar_loader()
            if calendar is not None:
                upcoming = [{"kind": e.kind, "at_utc": e.at.isoformat()} for e in calendar.upcoming(last.closed_at, 3)]
        budget = Budget(setup.budget.daily_usd, setup.budget.experiment_usd, config["max_call_usd"])
        estimate = getattr(setup.provider, "estimate_cost", None)
        if estimate is None:
            summary["models"] = "provider cannot project costs"
            return
        summary["models"] = "ran"
        skills_reports: dict[str, Report] = {}
        for variant in ("plain", "skills", "forced"):
            answers: dict[str, Action] = {}
            used: list[str] = []
            for agent in voters:
                inputs = build_inputs(agent, cycle_id=cycle_id, symbol=symbol, observed_at=last.closed_at,
                                      closed_prices=closes, headlines=headlines)
                tag = prompt_tag(agent)
                pack = {"skills": [], "sha256": ""}
                if variant in ("skills", "forced"):
                    if variant == "forced":
                        inputs["forced_direction"] = True  # same inputs and skills as the skills arm; only the answer rule differs
                    inputs["features"] = numeric
                    if agent == "news":
                        inputs["scheduled_us_announcements"] = upcoming
                    pack = skill_pack(agent, symbol, cycle_id, size=int(config["skill_pack_size"]),
                                      **({"root": self.skills_root} if self.skills_root else {}))
                    if pack["text"]:
                        family = ("Instrument family: Deriv synthetic index (simulated, 24/7, no news channel)."
                                  if is_synthetic(symbol) else "Instrument family: gold against the US dollar (XAUUSD).")
                        inputs["method_notes"] = family + "\n\n" + pack["text"]
                    used += pack["skills"]
                report = run_model(self.store, setup.provider, agent=agent, model=setup.models[agent],
                                   snapshot=inputs, budget=budget, projected_cost_usd=estimate(agent, inputs))
                failed = report.rationale in FAILURE_RATIONALES
                detail = {"rationale": report.rationale[:600], "evidence": list(report.evidence)[:8],
                          "score": report.score, "variant": variant, "prompt": tag, "model": setup.models[agent],
                          "skills": pack["skills"], "skills_sha256": pack["sha256"]}
                arm = f"{variant}:{agent}"
                if failed:
                    self._record(cycle_id, symbol, last.closed_at, arm, "WAIT", "model_failed", detail)
                    summary["arms"][arm] = "WAIT/model_failed"
                    continue
                answers[agent] = report.action
                if variant == "skills":
                    skills_reports[agent] = report
                propose(arm, report.action, detail)
            arm = f"{variant}:director"
            action, reason = consensus(answers)
            detail = {"rationale": reason, "votes": {a: v.value for a, v in answers.items()},
                      "variant": variant, "skills": sorted(set(used)), "director": "consensus@0.2.0"}
            if len(answers) < 2:
                self._record(cycle_id, symbol, last.closed_at, arm, "WAIT", "model_failed", detail)
                summary["arms"][arm] = "WAIT/model_failed"
            else:
                propose(arm, action, detail)
        self._ai_director(setup, symbol, cycle_id, last, plan, numeric, upcoming, skills_reports, baselines or {}, config,
                          propose, summary, budget)


FAILURE_RATIONALES = {
    "Call cost above configured cap", "Model budget exhausted", "Actual model cost exceeded budget",
    "Provider unavailable or invalid structured output",
}


# ---------------------------------------------------------------- status and the background loop

def status(store: ResearchStore, now: datetime | None = None) -> dict:
    now = now or utcnow()
    beat = json.loads(store.state_get("autopilot_heartbeat") or "{}")
    mode = get_mode(store)
    age = None
    if beat.get("at"):
        age = round((now - datetime.fromisoformat(beat["at"])).total_seconds())
    with store.journal.connect() as db:
        counts = {r["status"]: r["n"] for r in db.execute(
            "SELECT status, COUNT(*) AS n FROM decisions GROUP BY status")}
        today = db.execute("SELECT COUNT(*) FROM decisions WHERE at>=?", (now.strftime("%Y-%m-%d"),)).fetchone()[0]
        outcomes = db.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()[0]
    config = get_config(store)
    snapshot = json.loads(store.state_get("autopilot_positions") or "null") or {}
    floating = {p.get("ticket"): float(p.get("profit") or 0.0) for p in snapshot.get("positions", [])}
    groups: dict[str, list[dict]] = {}
    for order in store.open_orders():
        if order.get("basket_id"):
            groups.setdefault(order["basket_id"], []).append(order)
    baskets = []
    for basket_id, members in groups.items():
        meta = json.loads(store.state_get(f"basket:{basket_id}") or "null") or {}
        realised = store.basket_realised(basket_id)
        now_total = realised + sum(floating.get(m["position_ticket"], 0.0) for m in members)
        baskets.append({"basket_id": basket_id, "symbol": members[0]["symbol"], "side": members[0]["side"],
                        "members": len(members), "target_usd": meta.get("target_usd"), "total": round(now_total, 2),
                        "opened_at": members[0]["opened_at"]})
    # every instrument the pilot knows, analysed or not, so a ticked-off one can still be ticked back on
    known = list(dict.fromkeys([*DEFAULT_CONFIG["symbols"], *config["symbols"]]))
    return {"mode": mode, "active": mode != "off", "config": config, "known_symbols": known, "baskets": baskets,
            "alive": age is not None and age < 120, "heartbeat_age_seconds": age,
            "cycles": beat.get("cycles", 0), "errors": beat.get("errors", 0), "last_error": beat.get("last_error"),
            "last_cycle": beat.get("last_cycle", {}), "symbol_status": beat.get("symbol_status", {}),
            "decisions_by_status": counts, "decisions_today": today,
            "shadow_outcomes": outcomes, "costs": store.costs(),
            "demo_auto_available": store.state_get("autopilot_exec_ready") == "true",
            "demo_auto_reason": ("Les ordres partent sur le compte DÉMO, un à la fois par instrument, avec stop et objectif "
                                 "chez le courtier." if store.state_get("autopilot_exec_ready") == "true"
                                 else "Pont d'exécution MetaTrader indisponible dans ce processus."),
            "orders": store.order_summary(), "kill_switch": store.killed(),
            "keep_awake": store.state_get("autopilot_keep_awake") == "true"}


class AutopilotRunner:
    """Daemon thread that follows the persisted mode; safe to start once per process."""

    def __init__(self, autopilot: Autopilot, *, poll_seconds: float = 10.0, keep_awake=None):
        from .keep_awake import KeepAwake
        self.keep_awake = keep_awake if keep_awake is not None else KeepAwake()
        self.autopilot = autopilot
        self.poll = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_check: dict[str, datetime] = {}
        self._last_reconcile: datetime | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="autopilot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def tick(self) -> None:
        """One scheduling pass (public so tests and the CLI can drive it without a thread)."""
        store = self.autopilot.store
        now = self.autopilot.clock()
        # Windows must not fall asleep while the agents work or a position still needs following
        needed = get_mode(store) != "off" or bool(store.open_orders())
        holding = self.keep_awake.set(needed)
        if (store.state_get("autopilot_keep_awake") == "true") != holding:
            store.state_set("autopilot_keep_awake", "true" if holding else "false")
        self.autopilot.refresh_account()
        try:
            self.autopilot.handle_close_request()
            self.autopilot.check_baskets(self.autopilot.refresh_positions())
        except Exception as exc:  # noqa: BLE001
            store.journal.log("autopilot.error", "positions", {"error": type(exc).__name__, "message": str(exc)[:200]})
        if self.autopilot.executor is not None and (self._last_reconcile is None
                                                    or (now - self._last_reconcile).total_seconds() >= 60):
            self._last_reconcile = now
            try:
                self.autopilot.reconcile_orders()
            except Exception as exc:  # noqa: BLE001
                store.journal.log("autopilot.error", "reconcile", {"error": type(exc).__name__, "message": str(exc)[:200]})
        if get_mode(store) not in ("observe", "demo_auto"):
            return
        config = get_config(store)
        now = self.autopilot.clock()
        for symbol in config["symbols"]:
            step = TIMEFRAME_SECONDS[timeframe_for(config, symbol)]
            if get_mode(store) not in ("observe", "demo_auto"):  # switched off while we were working
                return
            if now < self._next_check.get(symbol, datetime.min.replace(tzinfo=timezone.utc)):
                continue
            try:
                result = self.autopilot.run_symbol(symbol)
            except Exception as exc:  # noqa: BLE001
                beat = self.autopilot.heartbeat()
                self.autopilot._beat(errors=beat.get("errors", 0) + 1, last_error=f"{type(exc).__name__}: {str(exc)[:200]}")
                store.journal.log("autopilot.error", symbol, {"error": type(exc).__name__, "message": str(exc)[:200]})
                self._next_check[symbol] = now + timedelta(seconds=60)
                continue
            beat = self.autopilot.heartbeat()
            seen = beat.get("symbol_status", {})
            seen[symbol] = {"status": result["status"], "at": now.isoformat(), "message": result.get("message", "")}
            self.autopilot._beat(symbol_status=seen)
            boundary = (int(now.timestamp()) // step + 1) * step + 5
            if result["status"] in ("ok", "halted"):
                self._next_check[symbol] = datetime.fromtimestamp(boundary, tz=timezone.utc)
            elif result["status"] == "no_new_bar":
                self._next_check[symbol] = now + timedelta(seconds=20)
            else:  # stale or data error: 24/7 synthetic indices are never closed, so look again quickly
                wait = 60 if is_synthetic(symbol) else min(300, step)
                self._next_check[symbol] = now + timedelta(seconds=wait)
        self.autopilot._beat()

    def _loop(self) -> None:
        try:
            self._run()
        finally:
            self.keep_awake.set(False)  # the request belongs to this thread: release it when the loop ends
            try:
                self.autopilot.store.state_set("autopilot_keep_awake", "false")
            except Exception:  # noqa: BLE001
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - never let the thread die silently, and never hide why
                try:
                    self.autopilot.store.journal.log("autopilot.error", "loop",
                                                     {"error": type(exc).__name__, "message": str(exc)[:200]})
                except Exception:  # noqa: BLE001
                    pass
            self._stop.wait(self.poll)
