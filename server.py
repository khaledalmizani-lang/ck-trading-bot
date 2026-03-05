import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"CK Trading Bot Running")
    def log_message(self, *args):
        pass

def start_server():
    server = HTTPServer(("0.0.0.0", 10000), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("[SERVER] HTTP server started on port 10000")
