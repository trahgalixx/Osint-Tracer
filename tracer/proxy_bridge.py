"""Jembatan proxy lokal.

Browser Playwright/Camoufox (Firefox) tidak mendukung SOCKS5 dengan username/password. Jembatan ini membuka proxy HTTP
tanpa login di 127.0.0.1 (hanya bisa diakses dari komputer ini), lalu meneruskan setiap koneksi ke proxy SOCKS5 Anda
lengkap dengan username/password. Nama domain di-resolve oleh proxy (remote DNS), jadi kueri DNS tidak bocor
dari komputer Anda.
"""
from __future__ import annotations

import select
import socket
import threading

import socks

from .log import log


class SocksAuthBridge:
    def __init__(self, host, port, username, password, socks_version=socks.SOCKS5):
        self.up = (socks_version, host, int(port), username, password)
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(128)
        self.port = self.srv.getsockname()[1]
        self._stop = threading.Event()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
        try:
            self.srv.close()
        except OSError:
            pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()

    # ------------------------------------------------------------------ internal
    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                cli, _ = self.srv.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(cli,), daemon=True).start()

    def _upstream(self, host, port):
        v, h, p, u, pw = self.up
        s = socks.socksocket()
        s.set_proxy(v, h, p, rdns=True, username=u, password=pw)
        s.settimeout(30)
        s.connect((host, port))
        s.settimeout(None)
        return s

    def _handle(self, cli):
        up = None
        try:
            cli.settimeout(30)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = cli.recv(65536)
                if not chunk:
                    return
                head += chunk
                if len(head) > 65536:
                    return
            line, _, rest = head.partition(b"\r\n")
            method, target, version = line.decode("latin-1").split(" ", 2)
            if method.upper() == "CONNECT":                       # HTTPS: terowongan
                host, _, port = target.rpartition(":")
                up = self._upstream(host.strip("[]"), int(port or 443))
                cli.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                extra = head.split(b"\r\n\r\n", 1)[1]
                if extra:
                    up.sendall(extra)
            else:                                                  # HTTP biasa (absolute URI)
                if "://" not in target:
                    cli.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                    return
                hostport = target.split("://", 1)[1].split("/", 1)[0]
                path = "/" + target.split("://", 1)[1].split("/", 1)[1] if "/" in target.split("://", 1)[1] else "/"
                host, _, port = hostport.partition(":")
                up = self._upstream(host, int(port or 80))
                up.sendall(f"{method} {path} {version}\r\n".encode("latin-1") + rest)
            cli.settimeout(None)
            self._pipe(cli, up)
        except Exception as e:
            try:
                cli.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            except OSError:
                pass
            log(f"[proxy] koneksi gagal: {type(e).__name__}: {str(e)[:120]}")
        finally:
            for s in (cli, up):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass

    def _pipe(self, a, b):
        socks_ = [a, b]
        while not self._stop.is_set():
            r, _, x = select.select(socks_, [], socks_, 60)
            if x or not r:
                if not r and not x:
                    continue
                return
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)


def needs_bridge(proxy: dict | None) -> bool:
    return bool(proxy and proxy.get("username") and proxy["server"].lower().startswith(("socks5://", "socks4://", "socks://")))


def make_bridge(proxy: dict) -> SocksAuthBridge:
    scheme, hostport = proxy["server"].split("://", 1)
    host, _, port = hostport.rpartition(":")
    ver = socks.SOCKS4 if scheme.lower() == "socks4" else socks.SOCKS5
    return SocksAuthBridge(host, port, proxy["username"], proxy.get("password", ""), ver)
