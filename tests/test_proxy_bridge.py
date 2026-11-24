"""Uji jembatan proxy: browser → HTTP lokal tanpa login → SOCKS5 dengan username/password.
Memakai server SOCKS5 tiruan (RFC 1928/1929) dan situs lokal. Jalankan: python -m tests.test_proxy_bridge"""
import os
import select
import socket
import struct
import threading

from flask import Flask
from werkzeug.serving import make_server

from tracer import tiktok_browser as TB
from tracer.proxy_bridge import make_bridge, needs_bridge

USER, PASS = "peneliti", "r@hasia"
SEEN = {"auth_ok": 0, "auth_bad": 0, "hosts": []}


def socks_server(port_holder):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(50)
    port_holder.append(srv.getsockname()[1])

    def handle(c):
        try:
            ver, n = c.recv(2)
            methods = c.recv(n)
            if 2 not in methods:
                c.sendall(b"\x05\xff")
                return
            c.sendall(b"\x05\x02")
            c.recv(1)
            u = c.recv(c.recv(1)[0]).decode()
            p = c.recv(c.recv(1)[0]).decode()
            if (u, p) != (USER, PASS):
                SEEN["auth_bad"] += 1
                c.sendall(b"\x01\x01")
                return
            SEEN["auth_ok"] += 1
            c.sendall(b"\x01\x00")
            _, cmd, _, atyp = c.recv(4)
            if atyp == 3:
                host = c.recv(c.recv(1)[0]).decode()
            elif atyp == 1:
                host = socket.inet_ntoa(c.recv(4))
            port = struct.unpack(">H", c.recv(2))[0]
            SEEN["hosts"].append(host)
            ip = "127.0.0.1" if host in ("situs.uji", "127.0.0.1") else host   # "DNS" dilakukan oleh proxy
            up = socket.create_connection((ip, port))
            c.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("0.0.0.0") + struct.pack(">H", 0))
            while True:
                r, _, _ = select.select([c, up], [], [], 10)
                if not r:
                    break
                for s in r:
                    d = s.recv(65536)
                    if not d:
                        return
                    (up if s is c else c).sendall(d)
        except Exception:
            pass
        finally:
            c.close()

    def loop():
        while True:
            c, _ = srv.accept()
            threading.Thread(target=handle, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()


def main():
    app = Flask(__name__)
    app.get("/")(lambda: "<html><body><h1 id=ok>halaman lewat proxy</h1></body></html>")
    web = make_server("127.0.0.1", 0, app)
    wport = web.server_port
    threading.Thread(target=web.serve_forever, daemon=True).start()
    ph = []
    socks_server(ph)
    sport = ph[0]

    proxy = TB.parse_proxy(f"socks5://{USER}:{PASS.replace('@', '%40')}@127.0.0.1:{sport}")
    assert needs_bridge(proxy) and not needs_bridge({"server": "http://h:1", "username": "u"})
    TB.log = lambda m: None
    with make_bridge(proxy) as br:
        # 1. HTTP biasa (absolute URI)
        s = socket.create_connection(("127.0.0.1", br.port))
        s.sendall(f"GET http://situs.uji:{wport}/ HTTP/1.1\r\nHost: situs.uji:{wport}\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while chunk := s.recv(65536):
            data += chunk
        assert b"200 OK" in data and b"halaman lewat proxy" in data, data[:200]
        # 2. CONNECT (dipakai untuk HTTPS)
        s = socket.create_connection(("127.0.0.1", br.port))
        s.sendall(f"CONNECT situs.uji:{wport} HTTP/1.1\r\nHost: situs.uji:{wport}\r\n\r\n".encode())
        assert b"200 Connection established" in s.recv(1024)
        s.sendall(f"GET / HTTP/1.1\r\nHost: situs.uji\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while chunk := s.recv(65536):
            data += chunk
        assert b"halaman lewat proxy" in data
        # 3. browser sungguhan (Chromium juga tidak mendukung SOCKS dengan login → realistis)
        from playwright.sync_api import sync_playwright
        exe = "/opt/pw-browsers/chromium"
        with sync_playwright() as pw:
            b = pw.chromium.launch(**({"executable_path": exe} if os.path.isfile(exe) else {}))
            ctx = b.new_context(proxy={"server": br.url})
            page = ctx.new_page()
            page.goto(f"http://situs.uji:{wport}/")
            assert page.text_content("#ok") == "halaman lewat proxy"
            b.close()
    assert "situs.uji" in SEEN["hosts"], "nama domain harus di-resolve oleh proxy (tanpa bocor DNS lokal)"

    # 4. password salah → 502, bukan diam-diam lewat tanpa proxy
    bad = dict(proxy, password="salah")
    with make_bridge(bad) as br:
        s = socket.create_connection(("127.0.0.1", br.port))
        s.sendall(f"GET http://situs.uji:{wport}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        assert b"502" in s.recv(1024)
    assert SEEN["auth_bad"] >= 1
    web.shutdown()
    print(f"OK  — HTTP & CONNECT lewat jembatan, Chromium memuat halaman, DNS lewat proxy, "
          f"login SOCKS dipakai ({SEEN['auth_ok']}x), password salah ditolak")


if __name__ == "__main__":
    main()
