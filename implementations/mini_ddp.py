#!/usr/bin/env python3
"""Mini DDP API server — arranca instantáneo, sin imports pesados"""
import json, sys
from http.server import HTTPServer, BaseHTTPRequestHandler

class MiniDDP(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self._json({'ok': True, 'agent': 'vm-api-mini', 'ddp': 'v0.2'})
        elif self.path == '/ddp/health':
            self._json({'ok': True, 'version': 'ddp-v0.2'})
        else:
            self._json({'ok': True, 'path': self.path})
    
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.path == '/ddp/push':
            self._json({'status': 'ok', 'applied': len(body.get('entries', []))})
        elif self.path == '/ddp/sync':
            self._json({'ns': body.get('ns','?'), 'entries': [], 'more': False, 'since': '2026-07-17T00:00:00Z'})
        else:
            self._json({'ok': True, 'echo': body})
    
    def _json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
server = HTTPServer(('127.0.0.1', port), MiniDDP)
print(f'MINI DDP on :{port}', flush=True)
server.serve_forever()
