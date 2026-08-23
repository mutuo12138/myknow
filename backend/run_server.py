from a2wsgi import ASGIMiddleware
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from main import app, init_db, start_integrity_repair_background

init_db(repair=False)
start_integrity_repair_background()


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


server = make_server("127.0.0.1", 8765, ASGIMiddleware(app), server_class=ThreadingWSGIServer)
server.serve_forever()
