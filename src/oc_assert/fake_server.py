"""Fake OpenAI-compatible model server that asks OpenCode to run one bash command.

OpenCode 1.x and 2.x only send streaming POSTs to /v1/chat/completions, so
that is all this answers; anything else gets an empty JSON object.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# OpenCode 1.x calls its shell tool "bash"; 2.x calls it "shell".
SHELL_TOOLS = {"bash", "shell"}


def make_handler(cmd: str) -> type[BaseHTTPRequestHandler]:
    """Build a request handler that replies with a shell tool call for `cmd`.

    The first chat request that offers a shell tool gets the tool call; once a
    tool result comes back it answers "done", so the OpenCode run ends.
    """

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            body: Any = json.loads(self.rfile.read(int(self.headers["content-length"])))
            if not self.path.endswith("/chat/completions"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
                return
            tools = [t["function"]["name"] for t in body.get("tools") or []]
            tool = next((t for t in tools if t.lower() in SHELL_TOOLS), None)
            answered = body["messages"][-1]["role"] == "tool"
            if tool and not answered:
                args = json.dumps({"command": cmd, "description": "oc-assert probe"})
                call = {
                    "index": 0,
                    "id": "call_0",
                    "type": "function",
                    "function": {"name": tool, "arguments": args},
                }
                delta: dict[str, Any] = {"role": "assistant", "tool_calls": [call]}
                finish = "tool_calls"
            else:
                delta = {"role": "assistant", "content": "done"}
                finish = "stop"
            usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
            chunks: list[dict[str, Any]] = [
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                    "usage": usage,
                },
            ]
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            for chunk in chunks:
                chunk.update(
                    id="chatcmpl-0",
                    object="chat.completion.chunk",
                    created=0,
                    model="stub",
                )
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")

    return Handler


def start(cmd: str) -> tuple[ThreadingHTTPServer, int]:
    """Start a server for `cmd` on a free local port; returns (server, port).

    Binding port 0 lets the server own the socket, so parallel cases can't race
    for the same port. Call server.shutdown() when done.
    """
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cmd))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_port
