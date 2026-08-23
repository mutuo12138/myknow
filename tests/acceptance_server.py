from __future__ import annotations

import sys
from pathlib import Path

from a2wsgi import ASGIMiddleware
from wsgiref.simple_server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from main import app, init_db


init_db()
server = make_server("127.0.0.1", 8766, ASGIMiddleware(app))
server.serve_forever()
