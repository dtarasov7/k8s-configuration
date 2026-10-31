"""Local HTTPS transport fixture shared by transport and Ansible integration tests."""
import json
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import yaml
from support import FakeAPI
from access_manager.schema import AccessError
from access_manager.client import APIError


class HTTPFixture:
    def __init__(self, root):
        self.root = Path(root)
        self.api = FakeAPI()
        self.headers = []
        self.secret = "test-bearer-token-do-not-print"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(self.root / "server.key"),
                "-out",
                str(self.root / "server.crt"),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def do_PATCH(self):
                self.handle_request()

            def do_DELETE(self):
                self.handle_request()

            def handle_request(self):
                uri = urlsplit(self.path)
                fixture.headers.append(self.headers.get("Authorization"))
                if self.headers.get("Authorization") != "Bearer " + fixture.secret:
                    self.send_response(401)
                    self.end_headers()
                    return
                if uri.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://localhost:1/steal")
                    self.end_headers()
                    return
                if uri.path == "/forbidden":
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(json.dumps({"message": fixture.secret}).encode())
                    return
                body = None
                if self.headers.get("Content-Length"):
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                try:
                    result = fixture.api.request(
                        self.command,
                        uri.path,
                        body,
                        {k: v[0] for k, v in parse_qs(uri.query).items()},
                    )
                    code = 200
                except APIError as exc:
                    code, result = exc.status, {"message": "redacted fixture error"}
                except AccessError:
                    code, result = 500, {"message": "redacted fixture error"}
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(self.root / "server.crt"), str(self.root / "server.key"))
        self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.kubeconfig = self.root / "kubeconfig.yaml"
        self.doc = {
            "apiVersion": "v1",
            "kind": "Config",
            "current-context": "fixture",
            "contexts": [{"name": "fixture", "context": {"cluster": "fixture", "user": "fixture"}}],
            "clusters": [
                {
                    "name": "fixture",
                    "cluster": {
                        "server": "https://localhost:" + str(self.server.server_port),
                        "certificate-authority": "server.crt",
                    },
                }
            ],
            "users": [{"name": "fixture", "user": {"token": self.secret}}],
        }
        self.write_config()

    def write_config(self):
        self.kubeconfig.write_text(yaml.safe_dump(self.doc), encoding="utf-8")

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
