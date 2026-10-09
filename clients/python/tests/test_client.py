from __future__ import annotations

import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from attested_memory import Actor, AttestedMemoryError, Client, IntegrityError, content_hash
from attested_memory.cli import main


class Fake(BaseHTTPRequestHandler):
    """A stand-in for attestedmemory.net: records requests, answers like the real routes."""

    seen: list[dict] = []
    tamper = False

    def log_message(self, *args):  # silence
        pass

    def _reply(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _record(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        entry = {"method": self.command, "path": self.path,
                 "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}  # HTTP is case-blind
        Fake.seen.append(entry)
        return entry

    def do_POST(self):
        entry = self._record()
        if self.path == "/api/v1/trials":
            return self._reply(201, {"api_key": "ask_trial", "plan": "personal.trial.7d", "product": "personal",
                                     "expires_at": "2026-10-16T00:00:00Z", "key_id": "key_1"})
        if self.path == "/memory/api/memories":
            if entry["headers"].get("x-saas-key") != "ask_trial":
                return self._reply(401, {"detail": "SaaS API key is invalid or expired"})
            content = entry["body"]["content"]
            stored = "tampered" if Fake.tamper else content
            return self._reply(201, {"id": "mem_1", "title": entry["body"]["title"], "content": stored,
                                     "content_hash": content_hash(content),
                                     "truth": {"status": "unverified"}, "provenance": {"status": "attested"}})
        self._reply(404, {"detail": "not found"})

    def do_GET(self):
        self._record()
        if self.path.startswith("/memory/api/search"):
            return self._reply(200, {"items": [], "total": 0, "query": "x"})
        if self.path == "/memory/api/memories/mem_1":
            return self._reply(200, {"id": "mem_1", "content": "hello", "content_hash": content_hash("hello")})
        self._reply(404, {"detail": "not found"})


@pytest.fixture()
def server():
    Fake.seen, Fake.tamper = [], False
    httpd = HTTPServer(("127.0.0.1", 0), Fake)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_trial_then_write_read_search(server):
    client = Client(Actor.generate(), base_url=server)
    assert client.start_trial()["plan"] == "personal.trial.7d" and client.api_key == "ask_trial"
    unit = client.write("Supplier terms", "Net 30", tags=["finance"], source_refs=["contract-17"])
    assert unit["id"] == "mem_1" and client.read("mem_1")["content"] == "hello"
    assert client.search("supplier", limit=500)["total"] == 0
    assert "limit=100" in Fake.seen[-1]["path"]                        # clamped like the server
    nonces = [s["headers"]["x-actor-nonce"] for s in Fake.seen]
    assert len(set(nonces)) == len(nonces), "a proof was reused"
    assert Fake.seen[1]["body"]["source_refs"] == ["contract-17"]
    assert "x-saas-key" not in Fake.seen[0]["headers"]                 # the trial is claimed by the actor alone


def test_a_memory_whose_content_does_not_match_its_hash_is_refused(server):
    Fake.tamper = True
    client = Client(Actor.generate(), "ask_trial", base_url=server)
    with pytest.raises(IntegrityError):
        client.write("t", "original")


def test_errors_carry_the_status_and_the_services_reason(server):
    client = Client(Actor.generate(), "wrong", base_url=server)
    with pytest.raises(AttestedMemoryError) as caught:
        client.write("t", "x")
    assert caught.value.status == 401 and "invalid or expired" in caught.value.detail
    with pytest.raises(AttestedMemoryError, match="no API key"):
        Client(Actor.generate(), base_url=server).search()


def test_the_key_file_is_private_and_never_overwritten(tmp_path):
    actor = Actor.generate()
    path = actor.save(tmp_path / "actor.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert Actor.load(path).actor_id == actor.actor_id
    with pytest.raises(FileExistsError):
        Actor.generate().save(path)


def test_cli_init_trial_write(server, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ATTESTED_MEMORY_HOME", str(tmp_path))
    monkeypatch.delenv("ATTESTED_MEMORY_API_KEY", raising=False)
    assert main(["--url", server, "init"]) == 0
    assert main(["--url", server, "trial"]) == 0
    assert stat.S_IMODE(os.stat(tmp_path / "key.json").st_mode) == 0o600
    assert main(["--url", server, "write", "Title", "Body", "--tag", "a"]) == 0
    assert '"id": "mem_1"' in capsys.readouterr().out
