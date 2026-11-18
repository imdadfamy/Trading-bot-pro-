"""Optional FastAPI adapter for the same observation-only service."""
import os
from hmac import compare_digest
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .service import Service
from .local_env import load_local_env

load_local_env()
app = FastAPI(title="Trading Intelligence Pro", version="0.2.0")
app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_credentials=False, allow_methods=["GET", "PATCH", "POST"],
                   allow_headers=["X-Operator-Key", "X-Operator-Name", "Content-Type"])
service = Service(os.getenv("TIP_DB", "data/trading.db"))


def operator(key: str | None):
    expected = os.getenv("TIP_OPERATOR_KEY")
    if not expected or not key or not compare_digest(key, expected):
        raise HTTPException(403, "Operator authentication unavailable or invalid")


class Settings(BaseModel):
    model_by_agent: dict[str, str] = Field(default_factory=dict)
    daily_ai_limit_usd: float = Field(ge=0, le=10000, default=5)
    experiment_ai_limit_usd: float = Field(ge=0, le=10000, default=50)
    quote_max_age_seconds: float = Field(gt=0, le=60, default=5)
    mode: str = "observation"


@app.get("/health")
def health():
    return service.read("/health")


@app.get("/readiness")
def readiness():
    return service.read("/readiness")


@app.get("/dashboard")
def dashboard():
    return service.read("/dashboard")


@app.get("/market/snapshot")
def snapshot():
    return service.read("/market/snapshot")


@app.get("/market/candles")
def candles():
    return service.read("/market/candles")


@app.get("/news/events")
def news():
    return service.read("/news/events")


@app.get("/calendar/events")
def calendar():
    return service.read("/calendar/events")


@app.get("/sessions")
def sessions():
    return service.read("/sessions")


@app.get("/signals")
def signals():
    return service.read("/signals")


@app.get("/agents")
def agents():
    return service.read("/agents")


@app.get("/skills")
def skills():
    return service.read("/skills")


@app.get("/positions")
def positions():
    return service.read("/positions")


@app.get("/performance")
def performance():
    return service.read("/performance")


@app.get("/backtests")
def backtests():
    return service.read("/backtests")


@app.get("/experiments")
def experiments():
    return service.read("/experiments")


class ExperimentDraft(BaseModel):
    mode: str
    strategy_version: str
    code_version: str | None = None


@app.post("/experiments")
def draft_experiment(data: ExperimentDraft, x_operator_key: str | None = Header(default=None)):
    operator(x_operator_key)
    from .experiments import ExperimentManager
    try:
        return {"id": ExperimentManager(service.store).draft(data.model_dump()), "status": "draft"}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/costs")
def costs():
    return service.read("/costs")


@app.get("/memory")
def memory():
    return service.read("/memory")


@app.get("/alerts")
def alerts():
    return service.read("/alerts")


@app.get("/audit")
def audit(x_operator_key: str | None = Header(default=None)):
    operator(x_operator_key)
    return service.store.journal.events()


@app.get("/audit/integrity")
def audit_integrity(x_operator_key: str | None = Header(default=None)):
    operator(x_operator_key)
    return {"valid": service.store.journal.verify_audit()}


@app.get("/orders/intents")
def order_intents(x_operator_key: str | None = Header(default=None)):
    operator(x_operator_key)
    return service.read("/orders/intents")


@app.get("/export/signals.csv")
def export_signals(x_operator_key: str | None = Header(default=None)):
    operator(x_operator_key)
    from .exports import signals_csv
    return Response(content=signals_csv(service.store), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="signals.csv"'})


@app.get("/settings")
def settings(x_operator_key: str | None = Header(default=None)):
    operator(x_operator_key)
    return service.settings()


@app.patch("/settings")
def change_settings(data: Settings, expected_version: int,
                    x_operator_key: str | None = Header(default=None),
                    x_operator_name: str = Header(default="local-operator")):
    operator(x_operator_key)
    try:
        return service.update_settings(data.model_dump(), expected_version, x_operator_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/risk/kill-switch")
def kill_switch(x_operator_key: str | None = Header(default=None)):
    operator(x_operator_key)
    service.store.set_killed()
    return {"killed": True}
