"""Serve only the replay page on loopback for the Codex sidebar."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse

REPLAY_DIR = Path(__file__).resolve().parent / "replays"
PAGE = REPLAY_DIR / "replay.html"


def replay_page_path(path):
    path = Path(path)
    return REPLAY_DIR / path if not path.is_absolute() and path.parent == Path(".") else path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif route in ("/", "/" + PAGE.name):
            content = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", type=Path, default=PAGE,
                        help="Page to serve; bare filenames resolve under replays/")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    PAGE = replay_page_path(args.page).resolve(strict=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Chess replay ready at http://127.0.0.1:{args.port}/{PAGE.name}", flush=True)
    server.serve_forever()
