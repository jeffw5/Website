#!/usr/bin/env python3
"""
proxy.py — Simple GraphDB CORS Proxy
Serves static files AND proxies /graphdb/* requests to GraphDB
Eliminates browser CORS issues entirely.

Usage:
    python3 proxy.py

Then open: http://localhost:3000/model-manager.html
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.request
import urllib.error
import os

GRAPHDB_URL = "http://localhost:7200"
PORT = 3000

class ProxyHandler(SimpleHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/graphdb/'):
            self._proxy_request('GET')
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith('/graphdb/'):
            self._proxy_request('POST')
        else:
            super().do_POST()

    def do_PUT(self):
        if self.path.startswith('/graphdb/'):
            self._proxy_request('PUT')

    def do_DELETE(self):
        if self.path.startswith('/graphdb/'):
            self._proxy_request('DELETE')

    def _proxy_request(self, method):
        # Strip /graphdb prefix and forward to GraphDB
        target_path = self.path[len('/graphdb'):]
        target_url  = GRAPHDB_URL + target_path

        # Read request body if present
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length else None

        # Build forwarded request
        req = urllib.request.Request(target_url, data=body, method=method)

        # Forward relevant headers
        for header in ('Content-Type', 'Accept', 'Authorization'):
            val = self.headers.get(header)
            if val:
                req.add_header(header, val)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                response_body = resp.read()
                self.send_response(resp.status)
                self._cors_headers()
                # Forward content-type
                ct = resp.headers.get('Content-Type', 'application/json')
                self.send_header('Content-Type', ct)
                self.send_header('Content-Length', len(response_body))
                self.end_headers()
                self.wfile.write(response_body)

        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self._cors_headers()
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)

        except Exception as e:
            msg = str(e).encode()
            self.send_response(502)
            self._cors_headers()
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', len(msg))
            self.end_headers()
            self.wfile.write(msg)

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type,Accept,Authorization')

    def log_message(self, format, *args):
        # Suppress favicon noise; guard against non-string args (e.g. HTTPStatus)
        first = str(args[0]) if args else ''
        if 'favicon' not in first:
            super().log_message(format, *args)


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(('', PORT), ProxyHandler)
    print(f"✓ Proxy server running at http://localhost:{PORT}")
    print(f"✓ Forwarding /graphdb/* → {GRAPHDB_URL}")
    print(f"✓ Open: http://localhost:{PORT}/model-manager.html")
    print(f"  Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
