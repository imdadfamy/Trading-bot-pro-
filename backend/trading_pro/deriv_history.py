"""Read-only public candle history from Deriv's unauthenticated market-data WebSocket.

No account, token or order capability is involved: the endpoint is public and this module only
sends one ``ticks_history`` request. Public candles carry no bid/ask, so ``bid`` and ``ask`` are
set to the close and the data must never be used to study execution costs.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import re
import socket
import ssl
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .market import Candle

HOST = "api.derivws.com"
PATH = "/trading/v1/options/ws/public"
BROKER = "deriv-public"
GRANULARITIES = frozenset({60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 86400})
MAX_COUNT = 20000
PAGE_SIZE = 1000  # the endpoint returns at most 1000 candles per request
MAX_MESSAGE_BYTES = 8_000_000
SYMBOL = re.compile(r"^[A-Za-z0-9_]{2,32}$")
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
CSV_FIELDS = ["symbol", "opened_at", "closed_at", "open", "high", "low", "close",
              "bid", "ask", "broker", "tick_volume"]


class _WebSocket:
    """Minimal client WebSocket (RFC 6455) over an already connected TLS socket."""

    def __init__(self, sock):
        self.sock = sock
        self._buffer = b""

    def _exact(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("Connection closed by server")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def handshake(self, host: str, path: str) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            if len(head) > 16384:
                raise ConnectionError("Handshake response too large")
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed during handshake")
            head += chunk
        head, _, rest = head.partition(b"\r\n\r\n")
        self._buffer = rest
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in lines[0] + " ":
            raise ConnectionError(f"WebSocket upgrade refused: {lines[0][:80]}")
        headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:])}
        expected = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expected:
            raise ConnectionError("Invalid WebSocket handshake")

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        size = len(payload)
        if size < 126:
            header = bytes([0x80 | opcode, 0x80 | size])
        elif size < 65536:
            header = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", size)
        else:
            header = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", size)
        mask = os.urandom(4)
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode())

    def recv_text(self) -> str:
        parts: list[bytes] = []
        total = 0
        while True:
            first, second = self._exact(2)
            final, opcode, size = first & 0x80, first & 0x0F, second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._exact(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._exact(8))[0]
            if size > MAX_MESSAGE_BYTES:
                raise ConnectionError("WebSocket frame too large")
            mask = self._exact(4) if second & 0x80 else None
            data = self._exact(size)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x9:
                self._send_frame(0xA, data)
            elif opcode == 0x8:
                raise ConnectionError("Connection closed by server")
            elif opcode in (0x0, 0x1):
                total += len(data)
                if total > MAX_MESSAGE_BYTES:
                    raise ConnectionError("WebSocket message too large")
                parts.append(data)
                if final:
                    return b"".join(parts).decode("utf-8")

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        self.sock.close()


def _connect(timeout: float) -> _WebSocket:
    raw = socket.create_connection((HOST, 443), timeout=timeout)
    tls = ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
    tls.settimeout(timeout)
    ws = _WebSocket(tls)
    try:
        ws.handshake(HOST, PATH)
    except Exception:
        tls.close()
        raise
    return ws


def parse_candles(response: dict, *, symbol: str, granularity: int, now: datetime | None = None) -> list[Candle]:
    """Convert one ``ticks_history`` candle response; drop any candle still forming."""
    if response.get("error"):
        error = response["error"]
        raise RuntimeError(f"Deriv refused the request: {error.get('code')} {str(error.get('message'))[:120]}")
    rows = response.get("candles")
    if not isinstance(rows, list) or not rows:
        raise ValueError("No candles returned")
    now = now or datetime.now(timezone.utc)
    candles: list[Candle] = []
    for row in rows:
        opened = datetime.fromtimestamp(int(row["epoch"]), tz=timezone.utc)
        closed = opened + timedelta(seconds=granularity)
        if closed > now:
            continue
        close = float(row["close"])
        candles.append(Candle(symbol, opened, closed, float(row["open"]), float(row["high"]),
                              float(row["low"]), close, close, close, BROKER))
    if any(a.closed_at > b.opened_at for a, b in zip(candles, candles[1:])):
        raise ValueError("Candles are not chronological")
    if len({c.opened_at for c in candles}) != len(candles):
        raise ValueError("Duplicate candle times")
    if len(candles) < 2:
        raise ValueError("Fewer than two closed candles returned")
    return candles


def _ask(ws, request: dict, timeout: float) -> dict:
    ws.send_text(json.dumps(request))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = json.loads(ws.recv_text())
        if message.get("req_id") in (request["req_id"], None) and (
                message.get("msg_type") in ("candles", "ohlc") or "candles" in message or "error" in message):
            return message
    raise TimeoutError("No candle response before the deadline")


def fetch_candles(symbol: str, *, granularity: int = 60, count: int = 1000,
                  timeout: float = 15.0, connect=_connect, pause: float = 0.3) -> list[Candle]:
    """Fetch up to ``count`` closed candles, paging backwards in 1000-candle requests."""
    if not SYMBOL.match(symbol):
        raise ValueError("Invalid symbol")
    if granularity not in GRANULARITIES:
        raise ValueError(f"Granularity must be one of {sorted(GRANULARITIES)}")
    if not 2 <= count <= MAX_COUNT:
        raise ValueError(f"Count must be between 2 and {MAX_COUNT}")
    rows: dict[int, dict] = {}
    end: int | str = "latest"
    ws = connect(timeout)
    try:
        for page in range(1, (count // PAGE_SIZE) + 3):
            message = _ask(ws, {"ticks_history": symbol, "adjust_start_time": 1, "count": PAGE_SIZE,
                                "end": end, "start": 1, "style": "candles",
                                "granularity": granularity, "req_id": page}, timeout)
            if message.get("error"):
                if rows:
                    break
                parse_candles(message, symbol=symbol, granularity=granularity)
            page_rows = message.get("candles") or []
            before = len(rows)
            rows.update({int(r["epoch"]): r for r in page_rows})
            closed = [e for e in rows if e + granularity <= time.time()]
            if len(closed) >= count or len(rows) == before or len(page_rows) < PAGE_SIZE:
                break
            end = min(rows) - 1
            time.sleep(pause)
    finally:
        ws.close()
    ordered = [rows[e] for e in sorted(rows)]
    candles = parse_candles({"candles": ordered}, symbol=symbol, granularity=granularity)
    return candles[-count:]


def write_csv(candles: list[Candle], destination: str | Path, *, overwrite: bool = False) -> Path:
    path = Path(destination)
    with path.open("w" if overwrite else "x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(CSV_FIELDS)
        for c in candles:
            writer.writerow([c.symbol, c.opened_at.isoformat(), c.closed_at.isoformat(), c.open, c.high,
                             c.low, c.close, c.bid, c.ask, c.broker, c.tick_volume])
    return path
