"""Fake HTTP(S) import server for the push tests (standard library + cryptography)."""

from __future__ import annotations

import datetime
import ipaddress
import json
import ssl
import threading
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@dataclass
class Received:
    method: str
    path: str
    headers: dict[str, str]
    parts: list[dict] = field(default_factory=list)


def self_signed(directory: Path, host: str = "127.0.0.1") -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "snowth-test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(host))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


class FakeImportServer:
    def __init__(self, token: str | None = None, tls_dir: Path | None = None,
                 host: str = "127.0.0.1", port: int = 0) -> None:
        self.token = token
        self.received: list[Received] = []
        self.counters: dict[str, int] = {}
        self.cert: Path | None = None
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def reply(self, status: int, body: dict | None = None, headers=None) -> None:
                payload = json.dumps(body or {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(payload)

            def count(self, key: str) -> int:
                server.counters[key] = server.counters.get(key, 0) + 1
                return server.counters[key]

            def do_GET(self):
                if self.path == "/_received":
                    return self.reply(200, {"received": [
                        {"method": r.method, "path": r.path,
                         "files": [p["filename"] for p in r.parts if p["filename"]]}
                        for r in server.received]})
                server.received.append(Received("GET", self.path, dict(self.headers.items())))
                if self.path.startswith("/jobs/job-1"):
                    n = self.count("job-1")
                    status = ["queued", "running", "done"][min(n - 1, 2)]
                    return self.reply(200, {"state": {"status": status}})
                if self.path.startswith("/jobs/job-2"):
                    return self.reply(200, {"state": {"status": "failed"}})
                return self.reply(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                message = BytesParser(policy=email_policy).parsebytes(
                    f"Content-Type: {self.headers.get('Content-Type')}\r\n\r\n".encode() + body)
                parts = []
                if message.is_multipart():
                    for part in message.iter_parts():
                        parts.append({"name": part.get_param("name", header="content-disposition"),
                                      "filename": part.get_filename(),
                                      "content_type": part.get_content_type(),
                                      "content": part.get_payload(decode=True)})
                server.received.append(Received("POST", self.path, dict(self.headers.items()),
                                                parts))
                if server.token and self.headers.get("Authorization") != f"Bearer {server.token}":
                    return self.reply(401, {"error": "bad token"})
                path = self.path.split("?")[0]
                if path == "/ok":
                    return self.reply(201, {"imported": len(parts)})
                if path == "/async":
                    return self.reply(202, {"data": {"job": {"id": "job-1"}}})
                if path == "/async-fail":
                    return self.reply(202, {"data": {"job": {"id": "job-2"}}})
                if path == "/error":
                    return self.reply(500, {"error": "boom"})
                if path == "/redirect":
                    return self.reply(302, {}, {"Location": "https://elsewhere.example/import"})
                if path == "/toolarge":
                    return self.reply(413, {"error": "too large"})
                if path == "/ratelimit":
                    if self.count("ratelimit") == 1:
                        return self.reply(429, {}, {"Retry-After": "0"})
                    return self.reply(201, {"imported": 1})
                if path == "/flaky":
                    if self.count("flaky") == 1:
                        return self.reply(503)
                    return self.reply(201, {"imported": 1})
                return self.reply(404)

        self.host = host
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.scheme = "http"
        if tls_dir is not None:
            self.cert, key = self_signed(tls_dir, host)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(self.cert, key)
            self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
            self.scheme = "https"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.httpd.server_address[1]}"

    def __enter__(self) -> FakeImportServer:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def posts(self, path: str) -> list[Received]:
        return [r for r in self.received if r.method == "POST" and r.path.split("?")[0] == path]


def main() -> int:
    import argparse
    import time

    parser = argparse.ArgumentParser(description="Fake HTTPS import server (tests only).")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--cert-dir", required=True)
    parser.add_argument("--token")
    args = parser.parse_args()
    cert_dir = Path(args.cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    with FakeImportServer(args.token, cert_dir, args.host, args.port) as server:
        print(f"fake import server on {server.base_url}", flush=True)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
