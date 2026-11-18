import base64
import hashlib
import json
import re
import struct
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_pro import deriv_history as dh
from trading_pro.backtest import load_candles


def frame(payload: bytes, opcode=0x1, final=True) -> bytes:
    first = (0x80 if final else 0) | opcode
    size = len(payload)
    if size < 126:
        return bytes([first, size]) + payload
    if size < 65536:
        return bytes([first, 126]) + struct.pack(">H", size) + payload
    return bytes([first, 127]) + struct.pack(">Q", size) + payload


class FakeSocket:
    """Plays the server side: answers the upgrade, then serves prepared frames."""

    def __init__(self, frames: bytes, bad_accept=False, status="101 Switching Protocols"):
        self.frames, self.bad_accept, self.status = frames, bad_accept, status
        self.sent = b""
        self.pending = None
        self.closed = False

    def sendall(self, data):
        self.sent += data
        if self.pending is None and b"Sec-WebSocket-Key" in self.sent:
            key = re.search(rb"Sec-WebSocket-Key: (\S+)", self.sent).group(1).decode()
            accept = base64.b64encode(hashlib.sha1((key + dh._GUID).encode()).digest()).decode()
            if self.bad_accept:
                accept = "wrong"
            head = (f"HTTP/1.1 {self.status}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode()
            self.pending = head + self.frames

    def recv(self, size):
        data, self.pending = (self.pending or b"")[:size], (self.pending or b"")[size:]
        return data

    def close(self):
        self.closed = True


def opener(frames: bytes, **kwargs):
    def connect(timeout):
        ws = dh._WebSocket(FakeSocket(frames, **kwargs))
        ws.handshake(dh.HOST, dh.PATH)
        return ws
    return connect


def candle_message(count=5, granularity=60, forming=False):
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(seconds=granularity * (count + (0 if forming else 1)))
    rows = []
    for i in range(count + 1):
        price = 100 + i
        rows.append({"epoch": int((start + timedelta(seconds=granularity * i)).timestamp()),
                     "open": price, "high": price + 1, "low": price - 1, "close": price + .5})
    return {"msg_type": "candles", "req_id": 1, "candles": rows}


class DerivHistoryTests(unittest.TestCase):
    def test_fetch_drops_forming_candle_and_marks_source(self):
        message = candle_message(count=5, forming=True)
        candles = dh.fetch_candles("R_75", count=10,
                                   connect=opener(frame(json.dumps(message).encode())))
        self.assertEqual(len(candles), 5)
        self.assertTrue(all(c.broker == dh.BROKER and c.bid == c.ask == c.close for c in candles))
        self.assertTrue(all(c.closed_at <= datetime.now(timezone.utc) for c in candles))

    def test_pages_backwards_without_duplicates(self):
        base = int(datetime.now(timezone.utc).timestamp() // 60 * 60) - 3 * 86400

        def page(first, count):
            rows = [{"epoch": base + 60 * i, "open": 100, "high": 101, "low": 99, "close": 100.5}
                    for i in range(first, first + count)]
            return frame(json.dumps({"msg_type": "candles", "candles": rows}).encode())
        frames = page(500, 1000) + page(0, 501)  # newest page first, then older with one overlap
        candles = dh.fetch_candles("R_75", count=1200, connect=opener(frames), pause=0)
        self.assertEqual(len(candles), 1200)
        opens = [c.opened_at for c in candles]
        self.assertEqual(opens, sorted(set(opens)))
        self.assertEqual(candles[-1].opened_at, datetime.fromtimestamp(base + 60 * 1499, tz=timezone.utc))

    def test_fragmented_message_and_ping_are_handled(self):
        body = json.dumps(candle_message(count=4, forming=False)).encode()
        half = len(body) // 2
        frames = (frame(b"hi", opcode=0x9) + frame(body[:half], final=False) +
                  frame(body[half:], opcode=0x0))
        self.assertGreaterEqual(len(dh.fetch_candles("R_75", count=10, connect=opener(frames))), 2)

    def test_rejects_bad_input_without_connecting(self):
        def forbidden(timeout):
            raise AssertionError("must not connect")
        for kwargs in ({"symbol": "R 75; DROP"}, {"symbol": "R_75", "granularity": 61},
                       {"symbol": "R_75", "count": 1}, {"symbol": "R_75", "count": 20001}):
            with self.assertRaises(ValueError):
                dh.fetch_candles(connect=forbidden, **kwargs)

    def test_server_error_and_handshake_failures(self):
        error = frame(json.dumps({"req_id": 1, "error": {"code": "MarketIsClosed", "message": "closed"}}).encode())
        with self.assertRaises(RuntimeError):
            dh.fetch_candles("R_75", connect=opener(error))
        with self.assertRaises(ConnectionError):
            opener(b"", bad_accept=True)(1)
        with self.assertRaises(ConnectionError):
            opener(b"", status="403 Forbidden")(1)

    def test_oversized_frame_is_refused(self):
        header = bytes([0x81, 127]) + struct.pack(">Q", dh.MAX_MESSAGE_BYTES + 1)
        with self.assertRaises(ConnectionError):
            dh.fetch_candles("R_75", connect=opener(header))

    def test_csv_round_trips_and_refuses_overwrite(self):
        candles = dh.parse_candles(candle_message(count=4), symbol="R_75", granularity=60)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "r75.csv"
            dh.write_csv(candles, path)
            self.assertEqual([c.close for c in load_candles(path)], [c.close for c in candles])
            with self.assertRaises(FileExistsError):
                dh.write_csv(candles, path)
            dh.write_csv(candles, path, overwrite=True)


if __name__ == "__main__":
    unittest.main()
