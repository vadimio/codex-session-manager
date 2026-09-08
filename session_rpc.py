"""Bounded, sequential access to the installed Codex app-server protocol."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import time
from pathlib import Path
from typing import Any

from session_models import VERSION


class AppServer:
    def __init__(self, home: Path, timeout: float = 120):
        self.home = home
        self.timeout = timeout
        self.process = None
        self.selector = selectors.DefaultSelector()
        self.buffer = bytearray()
        self.errors = bytearray()
        self.request_id = 0

    def __enter__(self):
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.home)
        self.process = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            bufsize=0,
        )
        for pipe in (self.process.stdout, self.process.stderr):
            os.set_blocking(pipe.fileno(), False)
            self.selector.register(pipe, selectors.EVENT_READ)
        try:
            self.request(
                "initialize",
                {
                    "clientInfo": {"name": "local_session_manager", "version": VERSION},
                    "capabilities": {"experimentalApi": True},
                },
            )
            self._send({"method": "initialized"})
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _send(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b"\n")

    def request(self, method: str, params: dict[str, Any]):
        self.request_id += 1
        request_id = self.request_id
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            while b"\n" in self.buffer:
                raw, _, rest = self.buffer.partition(b"\n")
                self.buffer = bytearray(rest)
                message = json.loads(raw)
                if "method" in message and "id" in message:
                    # This utility never grants server-initiated approvals.
                    self._send(
                        {
                            "id": message["id"],
                            "error": {
                                "code": -32601,
                                "message": "Interactive request unsupported",
                            },
                        }
                    )
                elif message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError(f"Codex {method}: {message['error']}")
                    return message.get("result")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"Codex {method} timed out; its outcome may be unknown. Refresh before retrying."
                )
            if not self.selector.get_map():
                detail = self.errors.decode(errors="replace").strip()[-2000:]
                raise RuntimeError(f"Codex exited during {method}: {detail}")
            for key, _ in self.selector.select(remaining):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    self.selector.unregister(key.fileobj)
                elif key.fileobj is self.process.stderr:
                    self.errors.extend(chunk)
                    del self.errors[:-8192]
                else:
                    self.buffer.extend(chunk)
                    if len(self.buffer) > 64 * 1024 * 1024:
                        raise RuntimeError(
                            "Codex response exceeds 64 MiB; use paged history."
                        )

    def __exit__(self, *_):
        self.selector.close()
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                pipe.close()


def app_server_request(home: Path, method: str, params: dict[str, Any], timeout=120):
    with AppServer(home, timeout) as server:
        return server.request(method, params)
