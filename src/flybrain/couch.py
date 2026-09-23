"""The couch scene's server: stdlib HTTP plus a WebSocket written by hand.

`run.py --couch` starts one of these in a daemon thread on 127.0.0.1 and hands
the browser two things: the files under `scene/` over plain HTTP, and a live
feed over `/ws`.

The feed is server to client, except for two words: a browser may send one
text frame `{"cmd": "save"}` or `{"cmd": "pause"}` (the overlay's buttons).
Those are parsed on the client's reader thread and dropped into a small
bounded queue on the `Hub` that the loop drains between ticks; anything else a
client sends is ignored. There is one rule that shapes everything
here: **the game loop must never wait for a browser**. So the observer that
runs inside the loop only ever writes into a "latest" slot on the `Hub` and
notifies; one thread per connected client wakes up, copies whatever is newer
than what it has already sent, releases the lock, and writes to its own socket.
A client that has stopped reading fills its socket buffer, misses the write
deadline, and is dropped. Nothing about that reaches the loop.

The WebSocket half is small because it only needs the half of RFC 6455 a
browser makes us implement: the `Sec-WebSocket-Accept` handshake, unmasked
server-to-client text and binary frames with the 126 and 127 length forms, and
enough of the client direction to answer a ping, notice a close and read the
two commands.
"""

from __future__ import annotations

import base64
import hashlib
import json
import select
import socket
import struct
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .config import Config

# Bump when the shape of a message changes. The scene refuses a version it does
# not know rather than drawing nonsense. 2: the journey fields, the `status`
# message and the client commands.
PROTOCOL_VERSION = 2

# The only things a browser may ask for. Everything else is ignored.
COMMANDS = frozenset({"save", "pause"})
# Commands waiting for the loop. A browser hammering Save cannot grow this.
COMMAND_QUEUE = 16

WS_PATH = "/ws"

# RFC 6455 section 1.3: the magic string the accept key is derived with.
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

# The first byte of a binary message says what the rest of it is. One kind so
# far: a raw 160x144 grayscale video frame.
VIDEO_MESSAGE = 1

# A browser sends us almost nothing, so anything large is a bug or an attack.
MAX_CLIENT_FRAME = 1 << 16

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


# ---------------------------------------------------------------- framing ---


def accept_key(key: str) -> str:
    """The `Sec-WebSocket-Accept` value for a client's `Sec-WebSocket-Key`.

    RFC 6455's own worked example is in the tests: `dGhlIHNhbXBsZSBub25jZQ==`
    has to come back as `s3pPLMBiTxaQ9kYGzzhZRbK+xOo=`.
    """
    digest = hashlib.sha1((key.strip() + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(payload: bytes, opcode: int = OP_TEXT) -> bytes:
    """One unmasked server-to-client frame, FIN set, no fragmentation.

    Three length forms, and the boundaries are exactly where the RFC puts them:
    up to 125 inline, up to 65535 in two bytes after a 126, anything larger in
    eight bytes after a 127.
    """
    size = len(payload)
    head = bytearray((0x80 | opcode,))
    if size < 126:
        head.append(size)
    elif size <= 0xFFFF:
        head.append(126)
        head += struct.pack("!H", size)
    else:
        head.append(127)
        head += struct.pack("!Q", size)
    return bytes(head) + payload


def _read_exactly(reader, count: int) -> bytes:
    data = reader.read(count)
    if data is None or len(data) < count:
        raise ConnectionError("the client hung up mid-frame")
    return data


def read_client_frame(reader) -> tuple[int, bytes] | None:
    """One frame from the client direction, unmasked. None at end of stream.

    Client frames are always masked; we accept an unmasked one too rather than
    closing the connection over it, because nothing here trusts the payload.
    """
    head = reader.read(2)
    if not head or len(head) < 2:
        return None
    opcode = head[0] & 0x0F
    masked = bool(head[1] & 0x80)
    size = head[1] & 0x7F
    if size == 126:
        size = struct.unpack("!H", _read_exactly(reader, 2))[0]
    elif size == 127:
        size = struct.unpack("!Q", _read_exactly(reader, 8))[0]
    if size > MAX_CLIENT_FRAME:
        raise ValueError(f"client frame of {size} bytes is far past anything a browser sends")
    mask = _read_exactly(reader, 4) if masked else b""
    payload = _read_exactly(reader, size) if size else b""
    if masked and payload:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return opcode, payload


def parse_command(payload: bytes) -> str | None:
    """`{"cmd": "save"}` or `{"cmd": "pause"}` -> the word, anything else ->
    None. Never raises: this runs on bytes a browser tab chose to send."""
    if len(payload) > 256:
        return None
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(message, dict):
        return None
    command = message.get("cmd")
    return command if isinstance(command, str) and command in COMMANDS else None


def send_all(sock: socket.socket, data: bytes, timeout: float) -> None:
    """Write every byte or raise, with a deadline on the whole write.

    This is the piece that makes a slow client harmless. `select` says whether
    the kernel will take more bytes right now; if it will not say so before the
    deadline, the caller drops the client instead of waiting on it.
    """
    view = memoryview(data)
    deadline = time.monotonic() + timeout
    while view:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("websocket client is not draining its socket")
        if not select.select([], [sock], [], left)[1]:
            continue
        sent = sock.send(view)
        if sent <= 0:
            raise ConnectionError("socket closed while writing")
        view = view[sent:]


# -------------------------------------------------------------------- hub ---


class Hub:
    """The latest-state slot between the game loop and the client threads.

    One slot per kind of message ("hello", "state", "video"), each holding the
    already-framed bytes and a sequence number from one shared counter. A
    publisher overwrites a slot; it never queues, so a loop running faster than
    a browser can draw simply skips frames instead of building a backlog.

    Sequence numbers are shared across slots so a client that has just
    connected, or has fallen behind, gets what it missed in the order it was
    published: the hello first, then the picture, then the numbers.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._slots: dict[str, tuple[int, bytes]] = {}
        self._seq = 0
        self._stopped = False
        self._clients = 0
        self.messages_sent = 0  # frames written to a socket, summed over clients
        self.clients_dropped = 0
        self._commands: deque[str] = deque(maxlen=COMMAND_QUEUE)
        self.commands_received = 0
        self.frames_ignored = 0  # client text frames that were not a command

    # -- the loop's side (never blocks on a socket) ------------------------

    def publish(self, slot: str, framed: bytes) -> None:
        with self._cond:
            if self._stopped:
                return
            self._seq += 1
            self._slots[slot] = (self._seq, framed)
            self._cond.notify_all()

    @property
    def clients(self) -> int:
        return self._clients

    def latest(self, slot: str) -> bytes | None:
        """The framed bytes currently in a slot. For tests and diagnostics."""
        with self._cond:
            held = self._slots.get(slot)
            return held[1] if held else None

    def take_commands(self) -> list[str]:
        """Every command a browser has sent since the last call, oldest
        first. The loop's side: it never blocks for longer than a lock."""
        with self._cond:
            if not self._commands:
                return []
            taken = list(self._commands)
            self._commands.clear()
            return taken

    # -- a client thread's side --------------------------------------------

    def push_command(self, command: str) -> None:
        with self._cond:
            self._commands.append(command)
            self.commands_received += 1

    def ignored(self) -> None:
        with self._cond:
            self.frames_ignored += 1

    def take(self, seen: dict[str, int], timeout: float) -> list[bytes] | None:
        """Everything newer than `seen`, oldest first. None once stopped.

        Waits up to `timeout` for something new, so a sender thread notices a
        shutdown without anything having to interrupt its socket.
        """
        with self._cond:
            if not self._stopped and not self._fresh(seen):
                self._cond.wait(timeout)
            if self._stopped:
                return None
            pending = sorted(
                (seq, name, data) for name, (seq, data) in self._slots.items() if seq > seen.get(name, 0)
            )
            for seq, name, _ in pending:
                seen[name] = seq
            return [data for _, _, data in pending]

    def _fresh(self, seen: dict[str, int]) -> bool:
        return any(seq > seen.get(name, 0) for name, (seq, _) in self._slots.items())

    def note_sent(self, count: int = 1) -> None:
        with self._cond:
            self.messages_sent += count

    def joined(self) -> None:
        with self._cond:
            self._clients += 1

    def left(self, dropped: bool) -> None:
        with self._cond:
            self._clients -= 1
            if dropped:
                self.clients_dropped += 1

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()


# ----------------------------------------------------------------- server ---


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # A WebSocket handler thread lives as long as its browser tab, so closing
    # the server must not try to join them.
    block_on_close = False
    # HTTPServer sets SO_REUSEADDR, and on Windows that lets a SECOND copy of
    # the scene bind the same port while the first is still serving: the
    # browser then lands on whichever one accepts, and shows the wrong run.
    # Measured: a two-hour-old watch run and a fresh replay both "listening"
    # on 8765. Exclusive use makes the second copy fail with the message in
    # CouchServer.__init__ instead.
    allow_reuse_address = False
    couch: CouchServer

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "flybrain-couch"
    sys_version = ""

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence. The terminal belongs to the HUD while a run is going."""

    @property
    def couch(self) -> CouchServer:
        return self.server.couch  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path == WS_PATH:
            self._websocket()
        else:
            self._static(path)

    # -- static files ------------------------------------------------------

    def _static(self, path: str) -> None:
        root = self.couch.root
        if path in ("", "/"):
            path = "/index.html"
        try:
            target = (root / path.lstrip("/")).resolve()
        except (OSError, ValueError):
            self._plain(400, "that is not a path")
            return
        if target != root and not target.is_relative_to(root):
            self._plain(403, "the scene folder is the whole web root")
            return
        if not target.is_file():
            self._plain(404, f"no such file: {path}")
            return
        self._body(200, target.read_bytes(), MIME.get(target.suffix.lower(), "application/octet-stream"))

    def _plain(self, code: int, text: str) -> None:
        self._body(code, text.encode("utf-8"), "text/plain; charset=utf-8")

    def _body(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- the upgrade -------------------------------------------------------

    def _websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or (self.headers.get("Upgrade") or "").lower() != "websocket":
            self._plain(400, "this endpoint speaks websocket only")
            return
        # From here the socket is ours. Nothing may touch self.wfile again:
        # the base class flushes it after do_GET returns, and an empty buffer
        # is the only thing that flush can do without upsetting the framing.
        self.close_connection = True
        handshake = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(key)}\r\n"
            "\r\n"
        ).encode("ascii")
        try:
            self.connection.sendall(handshake)
        except OSError:
            return
        self.couch.serve_client(self)


class CouchServer:
    """HTTP for `scene/`, WebSocket on `/ws`, both on one loopback port."""

    def __init__(
        self,
        cfg: Config | None = None,
        scene_dir: str | Path | None = None,
        hub: Hub | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self.cfg = cfg or Config()
        self.hub = hub or Hub()
        default_scene = Path(__file__).resolve().parents[2] / "scene"
        self.root = Path(scene_dir or default_scene).resolve()
        self.host = self.cfg.couch_host if host is None else host
        wanted = self.cfg.couch_port if port is None else port
        try:
            self._server = _Server((self.host, wanted), _Handler)
        except OSError as error:
            raise OSError(
                f"cannot listen on {self.host}:{wanted} ({error}). "
                "Another copy of the scene is probably still running; "
                "close it or pass --couch-port with a different number."
            ) from error
        self._server.couch = self
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> CouchServer:
        self._thread = threading.Thread(target=self._server.serve_forever, name="couch-http", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop accepting, wake every client thread, release the port."""
        self.hub.stop()
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- one connected browser ---------------------------------------------

    def serve_client(self, handler: _Handler) -> None:
        """Runs in the handler's own thread until the tab closes or we drop it.

        The socket is written from here and read from a small second thread,
        because the client direction carries only a ping, a close or one of
        the two commands, and none of them should be able to stall the feed.
        """
        sock = handler.connection
        lock = threading.Lock()
        stop = threading.Event()

        def send(framed: bytes) -> None:
            with lock:
                send_all(sock, framed, self.cfg.couch_send_timeout)

        reader = threading.Thread(
            target=self._read_client, args=(handler, send, stop), name="couch-ws-read", daemon=True
        )
        reader.start()
        self.hub.joined()
        dropped = False
        seen: dict[str, int] = {}
        try:
            while not stop.is_set():
                batch = self.hub.take(seen, self.cfg.couch_wait)
                if batch is None:
                    break
                for framed in batch:
                    send(framed)
                if batch:
                    self.hub.note_sent(len(batch))
        except (OSError, TimeoutError, ValueError):
            dropped = True
        finally:
            stop.set()
            self.hub.left(dropped)
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            reader.join(timeout=1.0)

    def _read_client(self, handler: _Handler, send, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                frame = read_client_frame(handler.rfile)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == OP_CLOSE:
                    break
                if opcode == OP_PING:
                    send(encode_frame(payload[:125], OP_PONG))
                elif opcode == OP_TEXT:
                    command = parse_command(payload)
                    if command is None:
                        self.hub.ignored()
                    else:
                        self.hub.push_command(command)
                # Everything else a client might send is ignored on purpose.
        except (OSError, TimeoutError, ValueError):
            pass
        finally:
            stop.set()
