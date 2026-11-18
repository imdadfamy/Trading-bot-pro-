"""Load a restricted local secret file without installing python-dotenv."""
from __future__ import annotations
import os
from pathlib import Path

ALLOWED = frozenset({
    "OPENAI_API_KEY", "TIP_NEWSAPI_KEY", "TIP_TRADING_ECONOMICS_KEY",
    "TIP_MT5_DEMO_LOGIN", "TIP_MT5_DEMO_SERVER", "TIP_MT5_DEMO_PASSWORD",
    "TIP_OPERATOR_KEY",
})
DEFAULT_PATH = Path(__file__).resolve().parents[2] / ".env.local"


def load_local_env(path: Path = DEFAULT_PATH) -> tuple[str, ...]:
    """Load nonempty known values; the existing process environment has priority."""
    if not path.is_file():
        return ()
    loaded = []
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env.local line {number}")
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name not in ALLOWED or "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError(f"Unsupported .env.local variable on line {number}")
        if not value:
            continue
        if value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return tuple(loaded)
