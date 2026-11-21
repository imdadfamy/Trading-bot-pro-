"""Application read models shared by the API and CLI."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from .market import session_label, sessions_at
from .store import ResearchStore


DEFAULT_RISK = {"risk_per_trade": 0.005, "max_daily_loss": 0.02, "max_open_risk": 0.01, "max_positions": 2,
                "max_spread": 0.0, "fixed_lot": None, "commission_per_lot": 0.0, "slippage_ticks": 2.0}
RISK_RANGES = {"risk_per_trade": (0.0005, 0.02), "max_daily_loss": (0.002, 0.10), "max_open_risk": (0.0005, 0.05),
               "max_positions": (1, 10), "max_spread": (0, 100000), "commission_per_lot": (0, 1000),
               "slippage_ticks": (0, 1000)}


def validate_risk(risk) -> dict:
    """Operator-editable risk level. Ranges are guard rails, not advice; see docs for the specification defaults."""
    if not isinstance(risk, dict) or set(risk) != set(DEFAULT_RISK):
        raise ValueError("Risk settings must contain exactly: " + ", ".join(DEFAULT_RISK))
    for key, (low, high) in RISK_RANGES.items():
        value = risk[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError(f"Invalid risk setting {key}: expected a number between {low} and {high}")
    if int(risk["max_positions"]) != risk["max_positions"]:
        raise ValueError("max_positions must be a whole number")
    lot = risk["fixed_lot"]
    if lot is not None and (isinstance(lot, bool) or not isinstance(lot, (int, float)) or not 0.01 <= lot <= 100):
        raise ValueError("fixed_lot must be empty (volume computed from the risk) or between 0.01 and 100")
    if risk["max_open_risk"] < risk["risk_per_trade"]:
        raise ValueError("max_open_risk cannot be below risk_per_trade")
    return dict(risk)


class Service:
    def __init__(self, database: str, skills_root: str | None = None):
        self.store = ResearchStore(database)
        self.skills_root = Path(skills_root) if skills_root else Path(__file__).resolve().parents[2] / "skills"

    NOISY_EVENTS = {"autopilot.decision", "autopilot.cycle", "autopilot.scored", "market.snapshot", "signal.created",
                    "model.compared", "order.reserved", "order.result"}
    VOTE_ARMS = {"graph": "skills:graph", "quant": "skills:quant", "news": "skills:news", "director": "skills:director",
                 "ai_director": "ai:director"}

    def latest_votes(self) -> dict:
        """Latest real answer of each role, from the pilot's ledger (a failed model call is not an answer)."""
        votes = {}
        with self.store.journal.connect() as db:
            for role, arm in self.VOTE_ARMS.items():
                row = db.execute("SELECT action, symbol, at FROM decisions WHERE arm=? AND status<>'model_failed' "
                                 "ORDER BY at DESC LIMIT 1", (arm,)).fetchone()
                if row:
                    votes[role] = dict(row)
        return votes

    def dashboard(self):
        from . import autopilot
        quote = self.store.latest_snapshot()
        status = autopilot.status(self.store)
        events = [e for e in self.store.journal.events(400) if e["kind"] not in self.NOISY_EVENTS][:30]
        account = json.loads(self.store.state_get("autopilot_account") or "null")
        fresh_account = False
        if account and account.get("at"):  # the account was read from MetaTrader in the last ten minutes
            from datetime import datetime, timezone
            fresh_account = (datetime.now(timezone.utc) - datetime.fromisoformat(account["at"])).total_seconds() < 600
        return {"mode": status["mode"], "broker": "connected" if (status["alive"] or fresh_account) else "disconnected",
                "kill_switch": self.store.killed(), "symbol": (quote or {}).get("symbol"), "live_trading": False,
                "snapshot": quote, "pending_order_intents": len(self.store.journal.pending_intents()),
                "agents": ["graph", "news", "quant", "risk", "director"], "events": events,
                "account": account,
                "latest_votes": self.latest_votes(),
                "decisions_total": sum(status["decisions_by_status"].values()),
                "signal_count": len(self.store.recent("signals", 500)), "costs": self.store.costs()}

    def settings(self):
        with self.store.journal.connect() as db:
            row = db.execute("SELECT version,payload FROM settings ORDER BY version DESC LIMIT 1").fetchone()
            defaults = {"mode": "observation", "model_by_agent": {}, "daily_ai_limit_usd": 5,
                        "experiment_ai_limit_usd": 50, "quote_max_age_seconds": 5,
                        "ai_cap_enabled": True, "risk": dict(DEFAULT_RISK)}
            if not row:
                return {"version": 0, "settings": defaults}
            stored = json.loads(row["payload"])
            return {"version": row["version"],
                    "settings": {**defaults, **stored, "risk": {**DEFAULT_RISK, **stored.get("risk", {})}}}

    def model_budget(self):
        from .models import Budget
        config = self.settings()["settings"]
        if not config.get("ai_cap_enabled", True):  # operator removed the ceiling: spend is only measured
            return Budget(float("inf"), float("inf"))
        return Budget(config["daily_ai_limit_usd"], config["experiment_ai_limit_usd"])

    def limits(self):
        """Risk limits for the risk engine, from the versioned operator settings."""
        from .core import Limits
        config = self.settings()["settings"]
        risk = config["risk"]
        # The risk engine needs a finite AI ceiling: with the cap removed, a limit no spend can reach.
        ai_ceiling = config["experiment_ai_limit_usd"] if config.get("ai_cap_enabled", True) else 1e12
        return Limits(risk_per_trade=risk["risk_per_trade"], max_daily_loss=risk["max_daily_loss"],
                      max_open_risk=risk["max_open_risk"], max_positions=int(risk["max_positions"]),
                      max_spread=risk["max_spread"], max_quote_age_seconds=config["quote_max_age_seconds"],
                      max_ai_spend=ai_ceiling)

    def update_settings(self, data: dict, expected_version: int, author: str):
        required = {"mode", "model_by_agent", "daily_ai_limit_usd", "experiment_ai_limit_usd", "quote_max_age_seconds"}
        optional = {"ai_cap_enabled", "risk"}
        if not required <= set(data) or set(data) - required - optional or data.get("mode") != "observation":
            raise ValueError("Only complete observation-mode settings are supported")
        if "ai_cap_enabled" in data and not isinstance(data["ai_cap_enabled"], bool):
            raise ValueError("ai_cap_enabled must be true or false")
        if "risk" in data:
            data = {**data, "risk": validate_risk(data["risk"])}
        models = data.get("model_by_agent")
        if not isinstance(models, dict) or set(models) - {"graph", "news", "quant", "risk", "director"}:
            raise ValueError("Unknown model assignment")
        if any(not isinstance(v, str) or len(v) > 100 for v in models.values()):
            raise ValueError("Invalid model name")
        for key, maximum in (("daily_ai_limit_usd", 10000), ("experiment_ai_limit_usd", 10000), ("quote_max_age_seconds", 60)):
            number = data[key]
            minimum = 0 if key != "quote_max_age_seconds" else 0.001
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not minimum <= number <= maximum:
                raise ValueError(f"Invalid {key}")
        if not isinstance(author, str) or not 1 <= len(author) <= 100:
            raise ValueError("Operator identity required")
        with self.store.journal.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT COALESCE(MAX(version),0) FROM settings").fetchone()[0]
            if current != expected_version:
                raise RuntimeError("Configuration version changed")
            version = current + 1
            db.execute("INSERT INTO settings VALUES(?,?,?)", (version, datetime.now(timezone.utc).isoformat(), json.dumps(data)))
        self.store.journal.log("settings.changed", "settings", {"version": version, "author": author})
        return {"version": version}

    def positions_view(self) -> dict:
        """Open positions of the project: live prices from the pilot's snapshot, plan, time left, opposite-signal flag."""
        from datetime import datetime, timezone
        snap = json.loads(self.store.state_get("autopilot_positions") or "null") or {}
        live = {p.get("ticket"): p for p in snap.get("positions", [])}
        now = datetime.now(timezone.utc)
        rows = []
        for o in self.store.open_orders():
            p = live.get(o["position_ticket"], {})
            left = None
            if o["max_age_seconds"]:
                left = round(o["max_age_seconds"] - (now - datetime.fromisoformat(o["opened_at"])).total_seconds())
            conflict = json.loads(self.store.state_get(f"autopilot_conflict:{o['symbol']}") or "null")
            if conflict and conflict.get("ticket") != o["position_ticket"]:
                conflict = None
            rows.append({"symbol": o["symbol"], "arm": o["arm"], "side": o["side"], "volume": o["volume"],
                         "entry": p.get("price_open", o["entry"]), "price_current": p.get("price_current"),
                         "profit": p.get("profit"), "stop_loss": o["stop_loss"], "take_profit": o["take_profit"],
                         "opened_at": o["opened_at"], "seconds_left": left, "max_age_seconds": o["max_age_seconds"],
                         "live": bool(p), "conflict": conflict})
        profits = [r["profit"] for r in rows if isinstance(r["profit"], (int, float))]
        return {"at": snap.get("at"), "positions": rows, "floating_profit": round(sum(profits), 2) if profits else None,
                "close_requested": bool(self.store.state_get("autopilot_close_request"))}

    def overview(self) -> dict:
        """One card per instrument: price, recent closes, pilot status, latest answers, open positions."""
        from . import autopilot
        from .autopilot_features import has_family_word, is_synthetic
        config = autopilot.get_config(self.store)
        beat = json.loads(self.store.state_get("autopilot_heartbeat") or "{}")
        cards = []
        with self.store.journal.connect() as db:
            for symbol in config["symbols"]:
                rows = db.execute("SELECT payload FROM candles WHERE symbol=? AND broker<>'SYNTHETIC-NOT-A-BROKER' "
                                  "ORDER BY closed_at DESC LIMIT 60", (symbol,)).fetchall()
                bars = [json.loads(r["payload"]) for r in reversed(rows)]
                closes = [b["close"] for b in bars]
                votes = {}
                for role, arm in self.VOTE_ARMS.items():
                    row = db.execute("SELECT action, at FROM decisions WHERE symbol=? AND arm=? AND status<>'model_failed' "
                                     "ORDER BY at DESC LIMIT 1", (symbol, arm)).fetchone()
                    if row:
                        votes[role] = dict(row)
                shadow_open = db.execute("SELECT COUNT(*) FROM decisions WHERE symbol=? AND status='open'", (symbol,)).fetchone()[0]
                real = [dict(r) for r in db.execute(
                    "SELECT side, volume, entry, stop_loss, take_profit, opened_at FROM auto_orders "
                    "WHERE symbol=? AND state='open'", (symbol,))]
                if not is_synthetic(symbol):
                    family = "gold"
                elif has_family_word(symbol, ("boom",)):
                    family = "boom"
                elif has_family_word(symbol, ("crash",)):
                    family = "crash"
                elif has_family_word(symbol, ("drift",)):
                    family = "drift"
                else:
                    family = "volatility"
                last_cycle = (beat.get("last_cycle") or {}).get(symbol, {})
                cards.append({
                    "symbol": symbol, "family": family, "timeframe": autopilot.timeframe_for(config, symbol),
                    "closes": closes[-60:], "price": closes[-1] if closes else None,
                    "change_pct": round((closes[-1] / closes[0] - 1) * 100, 3) if len(closes) > 1 and closes[0] else None,
                    "last_bar": bars[-1]["closed_at"] if bars else None,
                    "status": (beat.get("symbol_status") or {}).get(symbol, {}).get("status", "waiting"),
                    "session": last_cycle.get("session"), "halt": last_cycle.get("halt") or "",
                    "votes": votes, "shadow_open": shadow_open, "real_positions": real})
        return {"instruments": cards}

    def candles_view(self, query: dict) -> dict:
        """Bars of ONE instrument (the pilot stores several), real ones first; fictitious example bars only as a fallback."""
        from . import autopilot
        config = autopilot.get_config(self.store)
        snapshot = self.store.latest_snapshot()
        symbol = (query.get("symbol") or [None])[0] or (snapshot or {}).get("symbol") or config["symbols"][0]
        with self.store.journal.connect() as db:
            rows = db.execute("SELECT payload FROM candles WHERE symbol=? AND broker<>'SYNTHETIC-NOT-A-BROKER' "
                              "ORDER BY closed_at DESC LIMIT 120", (symbol,)).fetchall()
            example = False
            if not rows:
                rows = db.execute("SELECT payload FROM candles WHERE symbol=? ORDER BY closed_at DESC LIMIT 120",
                                  (symbol,)).fetchall()
                example = bool(rows)
        return {"candles": [json.loads(r["payload"]) for r in reversed(rows)], "symbol": symbol,
                "symbols": config["symbols"], "timeframe": autopilot.timeframe_for(config, symbol), "live": False,
                "source": "jeu d'exemple fictif" if example else "MetaTrader (compte démo), bougies enregistrées"}

    def read(self, path: str, query: dict | None = None):
        query = query or {}
        if path == "/health":
            return {"status": "ok", "mode": "observation", "live_trading": False}
        if path == "/readiness":
            from .experiments import GATES
            from .integrations import credential_status
            from . import autopilot
            return {"ready_for_local_review": True, "ready_for_14_day_demo": False,
                    "execution_mode": autopilot.get_mode(self.store), "kill_switch": self.store.killed(),
                    "credentials": credential_status(),
                    "blocked_gates": list(GATES),
                    "note": "Gates need independent evidence; this endpoint does not attest external integrations"}
        if path == "/dashboard":
            return self.dashboard()
        if path == "/orders/intents":
            return self.store.journal.pending_intents()
        if path == "/market/snapshot":
            return {"snapshot": self.store.latest_snapshot(), "live": False}
        if path == "/market/candles":
            return self.candles_view(query)
        if path == "/market/overview":
            return self.overview()
        if path == "/news/events":
            from .core import utcnow
            return self.store.news_as_of(utcnow())
        if path == "/calendar/events":
            from .core import utcnow
            return self.store.calendar_as_of(utcnow())[-100:]
        if path == "/signals":
            return [json.loads(row["payload"]) for row in self.store.recent("signals")]
        if path == "/agents":
            return [json.loads(row["payload"]) for row in self.store.recent("agent_runs")]
        if path == "/positions":
            return {"positions": [], "connected": False, "reason": "MT5 reconciliation not configured"}
        if path == "/sessions":
            from .core import utcnow
            now = utcnow()
            return {"as_of": now.isoformat(), "active": sessions_at(now),
                    "primary": session_label(now), "broker_hours_verified": False}
        if path == "/costs":
            costs = self.store.costs()
            configured = self.settings()["settings"]
            daily_limit = configured["daily_ai_limit_usd"]
            experiment_limit = configured["experiment_ai_limit_usd"]
            if not configured.get("ai_cap_enabled", True):
                return {**costs, "cap_enabled": False, "daily_limit_usd": None, "experiment_limit_usd": None,
                        "daily_ratio": None, "experiment_ratio": None, "new_model_calls_blocked": False}
            return {**costs, "cap_enabled": True, "daily_limit_usd": daily_limit,
                    "experiment_limit_usd": experiment_limit,
                    "daily_ratio": costs["today_usd"]/daily_limit if daily_limit else None,
                    "experiment_ratio": costs["total_usd"]/experiment_limit if experiment_limit else None,
                    "new_model_calls_blocked": (daily_limit == 0 or experiment_limit == 0 or
                                                costs["today_usd"] >= daily_limit or costs["total_usd"] >= experiment_limit)}
        if path == "/performance":
            return {"metrics": None, "reason": "No validated demo fills or equity snapshots"}
        if path == "/backtests":
            return self.store.backtests()
        if path == "/announcements":
            from . import us_events
            from .core import utcnow
            try:
                return us_events.describe(us_events.load(), utcnow())
            except FileNotFoundError:
                return {"configured": False, "upcoming": [], "coverage": {}, "halt_reason": None, "blackout": None}
        if path == "/synthetic/reports":
            return self.store.synthetic_reports()
        if path == "/autopilot":
            from . import autopilot
            return autopilot.status(self.store)
        if path == "/autopilot/orders":
            return {"summary": self.store.order_summary(), "orders": self.store.orders()}
        if path == "/autopilot/positions":
            return self.positions_view()
        if path == "/autopilot/analyses":
            from . import autopilot_stats
            return autopilot_stats.recent_analyses(self.store)
        if path == "/autopilot/performance":
            from . import autopilot_stats
            return autopilot_stats.performance(self.store)
        if path == "/autopilot/decisions":
            from . import autopilot_stats
            return autopilot_stats.recent_decisions(self.store)
        if path == "/experiments":
            from .experiments import ExperimentManager
            return ExperimentManager(self.store).list()
        if path == "/skills":
            return json.loads((self.skills_root / "catalog.json").read_text(encoding="utf-8"))
        if path == "/memory":
            return [dict(row) for row in self.store.recent("memory")]
        if path == "/alerts":
            return [dict(row) for row in self.store.recent("alerts")]
        raise KeyError(path)
