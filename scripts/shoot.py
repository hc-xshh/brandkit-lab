#!/usr/bin/env python3
"""Full-page screenshots with zero third-party dependencies.

Talks to a headless Chrome/Chromium over the DevTools protocol. The websocket
client below is hand-rolled on top of ``socket`` + ``base64`` because the whole
point of this repository is that it runs with the standard library alone.

Usage
-----
    python3 scripts/shoot.py --out docs/img --size 1280x900 shotname=FILE [shotname=FILE ...]

Each argument of the form ``name=path`` is rendered at ``--size`` and written to
``<out>/<name>.png``. Exit code is non-zero if any shot could not be produced.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/opt/google/chrome/google-chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)


def find_chrome() -> str:
    env = os.environ.get("CHROME_BIN")
    if env and Path(env).exists():
        return env
    for cand in CHROME_CANDIDATES:
        found = shutil.which(cand)
        if found:
            return found
        if Path(cand).exists():
            return cand
    raise SystemExit("no chrome/chromium binary found (set CHROME_BIN)")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# --------------------------------------------------------------------------
# minimal websocket client (RFC 6455, client side only)
# --------------------------------------------------------------------------
class WebSocket:
    def __init__(self, url: str, timeout: float = 30.0) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "ws":
            raise ValueError(f"only ws:// supported, got {url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        self._buf = b""
        header = self._read_until(b"\r\n\r\n")
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"websocket handshake failed: {header[:200]!r}")
        self._id = 0

    # -- raw framing -------------------------------------------------------
    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise ConnectionError("websocket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_until(self, token: bytes) -> bytes:
        while token not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket closed during handshake")
            self._buf += chunk
        idx = self._buf.index(token) + len(token)
        out, self._buf = self._buf[:idx], self._buf[idx:]
        return out

    def send_text(self, text: str) -> None:
        payload = text.encode()
        mask = secrets.token_bytes(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_message(self) -> str:
        chunks: list[bytes] = []
        while True:
            b0, b1 = self._recv_exact(2)
            fin = bool(b0 & 0x80)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length) if length else b""
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:  # ping -> pong
                self.sock.sendall(bytes([0x8A, 0x80]) + secrets.token_bytes(4))
                continue
            if opcode == 0x8:
                raise ConnectionError("websocket closed by peer")
            if opcode in (0x1, 0x2, 0x0):
                chunks.append(payload)
                if fin:
                    return b"".join(chunks).decode("utf-8", "replace")

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self._id += 1
        msg_id = self._id
        self.send_text(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = json.loads(self.recv_message())
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"{method} failed: {data['error']}")
                return data.get("result", {})
        raise TimeoutError(f"{method} timed out")

    def wait_for_event(self, name: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = json.loads(self.recv_message())
            if data.get("method") == name:
                return data.get("params", {})
        raise TimeoutError(f"event {name} never arrived")

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.sock.close()


# --------------------------------------------------------------------------
def wait_for_devtools(port: int, timeout: float = 25.0) -> str:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 (localhost)
                return json.loads(resp.read())["webSocketDebuggerUrl"]
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(0.2)
    raise SystemExit(f"chrome devtools endpoint never came up: {last}")


def shoot(chrome: str, port: int, url: str, width: int, height: int, out: Path,
          full_page: bool = True) -> tuple[int, int]:
    browser = WebSocket(wait_for_devtools(port))
    try:
        target = browser.call("Target.createTarget", {"url": "about:blank"})
        target_id = target["targetId"]
        with urllib.request.urlopen(  # noqa: S310 (localhost)
            f"http://127.0.0.1:{port}/json/list", timeout=5
        ) as resp:
            pages = json.loads(resp.read())
        ws_url = next(
            (p["webSocketDebuggerUrl"] for p in pages if p.get("id") == target_id), None
        )
        if ws_url is None:
            raise RuntimeError("could not resolve page target websocket url")

        page = WebSocket(ws_url, timeout=60)
        try:
            page.call("Page.enable")
            page.call("Runtime.enable")
            page.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            page.call("Page.navigate", {"url": url})
            page.wait_for_event("Page.loadEventFired", timeout=30)
            # let layout settle (webfonts are absent by design; this is cheap)
            page.call(
                "Runtime.evaluate",
                {"expression": "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))",
                 "awaitPromise": True},
            )
            measured = page.call(
                "Runtime.evaluate",
                {
                    "expression": "Math.max(document.documentElement.scrollHeight,"
                    " document.body ? document.body.scrollHeight : 0)",
                    "returnByValue": True,
                },
            )
            content_height = int(measured.get("result", {}).get("value") or height)
            clip_height = max(height, content_height) if full_page else height
            shot = page.call(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "captureBeyondViewport": bool(full_page),
                    "clip": {
                        "x": 0,
                        "y": 0,
                        "width": width,
                        "height": clip_height,
                        "scale": 1,
                    },
                },
                timeout=60,
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(base64.b64decode(shot["data"]))
            return width, clip_height
        finally:
            page.close()
            with contextlib.suppress(Exception):
                browser.call("Target.closeTarget", {"targetId": target_id}, timeout=5)
    finally:
        browser.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/img", help="output directory for PNGs")
    ap.add_argument("--size", default="1280x900", help="viewport WxH (WxH)")
    ap.add_argument("--viewport-only", action="store_true", help="do not capture full page")
    ap.add_argument("shots", nargs="+", metavar="NAME=PATH", help="name=html file")
    args = ap.parse_args(argv)

    width, _, height = args.size.partition("x")
    width, height = int(width), int(height or 900)
    outdir = Path(args.out)
    chrome = find_chrome()
    port = free_port()

    proc = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--disable-lcd-text",
            "--allow-file-access-from-files",
            f"--window-size={width},{height}",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={Path(os.environ.get('TMPDIR', '/tmp')) / ('bk-chrome-' + str(port))}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    failures: list[str] = []
    try:
        for spec in args.shots:
            name, _, path = spec.partition("=")
            if not path:
                failures.append(f"{spec}: expected NAME=PATH")
                continue
            url = "file://" + str(Path(path).resolve())
            target = outdir / f"{name}.png"
            try:
                w, h = shoot(chrome, port, url, width, height, target,
                             full_page=not args.viewport_only)
                print(f"  ok   {name:28} {w}x{h}  -> {target}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name}: {exc}")
                print(f"  FAIL {name:28} {exc}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    if failures:
        print("\nscreenshot failures:", file=sys.stderr)
        for f in failures:
            print("  -", f, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
