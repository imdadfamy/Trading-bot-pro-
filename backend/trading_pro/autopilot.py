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

from .autopilot_features import atr, features, has_family_word, is_synthetic, skill_pack
from .agents import graph_agent
from .backtest import BacktestConfig, sma_signal
from .core import Action, Report, Snapshot, utcnow
from .market import Candle, session_label
from .models import Budget, run_model
from .prompts import build_inputs, prompt_tag
from .store import ResearchStore

MODES = ("off", "observe")
TIMEFRAME_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}
DEFAULT_CONFIG = {
    "symbols": ["Volatility 10 Index", "Boom 500 Index", "Crash 500 Index", "Drift Switch Index 10",
                "Drift Switch Index 20", "Drift Switch Index 30", "XAUUSD"], "timeframe": "M5", "bars": 300,
    # Drift Switch regimes last 10 to 30 minutes on average: M5 bars are too coarse, so they are read on M1 bars.
    "symbol_timeframes": {"Drift Switch Index 10": "M1", "Drift Switch Index 20": "M1", "Drift Switch Index 30": "M1"},
    "model_every_minutes": 30, "horizon_bars": 48, "stop_atr_multiple": 2.0, "reward_multiple": 2.0,
    "skill_pack_size": 3, "max_call_usd": 0.25,
}
CONFIG_LIMITS = {"model_every_minutes": (5, 1440), "horizon_bars": (4, 500), "stop_atr_multiple": (0.5, 10),
                 "reward_multiple": (0.5, 10), "skill_pack_size": (0, 8), "max_call_usd": (0.01, 5), "bars": (100, 1000)}
SPIKE_NAMES = ("boom", "crash", "jump", "dex")
EXPOSED_STATUSES = ("open", "resolved")  # statuses that count as a taken shadow trade


# ---------------------------------------------------------------- operational state

def get_mode(store: ResearchStore) -> str:
    mode = store.state_get("autopilot_mode", "off")
    return mode if mode in MODES else "off"


def set_mode(store: ResearchStore, mode: str, *, author: str) -> dict:
    if mode == "demo_auto":
        raise PermissionError("Automatic demo orders are not commissioned yet (step 3): only observation is available")
    if mode not in MODES:
        raise ValueError("Mode must be off or observe")
    if not isinstance(author, str) or not 1 <= len(author) <= 100:
        raise ValueError("Operator identity required")
    previous = get_mode(store)
    store.state_set("autopilot_mode", mode)
    store.journal.log("autopilot.mode_changed", "global", {"from": previous, "to": mode, "author": author})
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
            if (not isinstance(item, list) or not 1 <= len(item) <= 6
                    or any(not isinstance(s, str) or not 1 <= len(s) <= 60 for s in item)):
                raise ValueError("symbols must be 1 to 6 instrument names")
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


def trade_plan(candles: list[Candle], config: dict) -> dict | None:
    value = atr(candles)
    if not value or value <= 0:
        return None
    return {"stop_distance": round(config["stop_atr_multiple"] * value, 8), "reward_multiple": config["reward_multiple"],
            "horizon_bars": int(config["horizon_bars"]), "atr_14": round(value, 8)}


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
                 clock=utcnow, calendar_loader=None, skills_root=None):
        self.store = store
        self.fetch = fetch
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
            self.store.journal.log("autopilot.data_error", symbol, {"error": type(exc).__name__, "message": str(exc)[:200]})
            return {"symbol": symbol, "status": "data_error", "message": str(exc)[:200]}
        if len(candles) < 40:
            return {"symbol": symbol, "status": "data_error", "message": "fewer than 40 closed candles"}
        last = candles[-1]
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
                if scored and action != Action.WAIT and plan is not None:
                    with self.store.journal.connect() as db:
                        db.execute("INSERT OR IGNORE INTO direction_pending VALUES(?,?,?,?,?,?)",
                                   (decision_id, symbol, last.closed_at.isoformat(), action.value, horizon,
                                    plan["stop_distance"]))

            cross = sma_signal(BacktestConfig())(closes, candles)
            propose("rule:sma_cross", cross or "WAIT", {"rationale": "SMA 5/20 crossover on closed bars"})
            graph = graph_agent(closes)
            propose("det:graph", graph.action, {"rationale": graph.rationale})
            coin = "BUY" if int(sha256(cycle_id.encode()).hexdigest(), 16) % 2 else "SELL"
            propose("random:coin", coin, {"rationale": "seeded coin flip: the chance reference for the forced-direction arms"})
            self._model_arms(symbol, cycle_id, last, candles, config, propose, summary, scored)
        self.store.state_set(f"autopilot_last_bar:{symbol}", last.closed_at.isoformat())
        self.store.journal.log("autopilot.cycle", cycle_id, summary)
        beat = self.heartbeat()
        self._beat(cycles=beat.get("cycles", 0) + 1, last_cycle={**beat.get("last_cycle", {}), symbol: summary})
        return {"symbol": symbol, "status": "halted" if halt else "ok", **summary}

    # -- model arms
    def _model_arms(self, symbol, cycle_id, last, candles, config, propose, summary, scored):
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
    return {"mode": mode, "active": mode != "off", "config": get_config(store),
            "alive": age is not None and age < 120, "heartbeat_age_seconds": age,
            "cycles": beat.get("cycles", 0), "errors": beat.get("errors", 0), "last_error": beat.get("last_error"),
            "last_cycle": beat.get("last_cycle", {}), "symbol_status": beat.get("symbol_status", {}),
            "decisions_by_status": counts, "decisions_today": today,
            "shadow_outcomes": outcomes, "costs": store.costs(),
            "demo_auto_available": False,
            "demo_auto_reason": "Étape 3 : les ordres automatiques en démo ne sont pas encore commissionnés."}


class AutopilotRunner:
    """Daemon thread that follows the persisted mode; safe to start once per process."""

    def __init__(self, autopilot: Autopilot, *, poll_seconds: float = 10.0):
        self.autopilot = autopilot
        self.poll = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_check: dict[str, datetime] = {}

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
        if get_mode(store) != "observe":
            return
        config = get_config(store)
        now = self.autopilot.clock()
        for symbol in config["symbols"]:
            step = TIMEFRAME_SECONDS[timeframe_for(config, symbol)]
            if get_mode(store) != "observe":  # switched off while we were working
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
