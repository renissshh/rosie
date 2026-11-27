"""Shared by the end-to-end tests: a fake model, tiny HTTP servers, a config to start from.

The fake model is an OpenAI-compatible server (like Ollama's /v1) with a script:

    "add a task: X"  -> calls add_task(title=X)
    "remember: X"    -> calls remember_fact(text=X)   (the safety gate asks first)
    anything else    -> "You said: ..."
    after a tool ran -> "Done. (<what the tool returned>)"
"""

from __future__ import annotations

import http.server
import json
import os
import threading
from pathlib import Path

MODEL = "fake:e2e"


def fake_reply(messages: list[dict]) -> dict:
    last = messages[-1]
    if last["role"] == "tool":
        return {"role": "assistant", "content": f"Done. ({last['content']})"}
    text = str(last.get("content", ""))
    for prefix, tool, key in (
        ("add a task: ", "add_task", "title"),
        ("remember: ", "remember_fact", "text"),
    ):
        if text.lower().startswith(prefix):
            args = {key: text[len(prefix) :]}
            call = {
                "id": "call_1",
                "type": "function",
                "function": {"name": tool, "arguments": json.dumps(args)},
            }
            return {"role": "assistant", "content": None, "tool_calls": [call]}
    return {"role": "assistant", "content": f"You said: {text}"}


class FakeModel(http.server.BaseHTTPRequestHandler):
    def _json(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # `rosie doctor`'s model check: GET /v1/models
        self._json({"data": [{"id": MODEL}]})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length))
        message = fake_reply(request["messages"])
        self._json({"model": MODEL, "choices": [{"message": message}]})

    def log_message(self, *args) -> None:  # keep pytest output clean
        pass


def start_http(handler, port: int = 0) -> http.server.ThreadingHTTPServer:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def stop_http(server: http.server.ThreadingHTTPServer) -> None:
    server.shutdown()  # stops serving...
    server.server_close()  # ...and frees the port for the next test


def write_config(data: Path, model_url: str) -> Path:
    """A rosie.yaml with everything in `data` and the given model."""
    config = data / "rosie.yaml"
    config.write_text(
        "\n".join(
            [
                f'data_dir: "{data.as_posix()}"',
                "llm:",
                "  provider: ollama",
                f'  model: "{MODEL}"',
                f'  base_url: "{model_url}"',
                "day_blocks: []",
            ]
        ),
        encoding="utf-8",
    )
    return config


def clean_env() -> dict[str, str]:
    """This environment without ROSIE_* overrides, with UTF-8 output on Windows too."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ROSIE_")}
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env
