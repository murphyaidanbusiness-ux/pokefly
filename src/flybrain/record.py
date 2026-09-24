"""Renders the couch scene to an mp4 file with nobody at the keyboard.

`run.py --record out.mp4` and `scripts/render_shots.py` both come through
here. A headless Edge (or Chrome) draws the page at exactly the size of the
file, the Chrome DevTools Protocol hands every repaint over as a JPEG
(`Page.startScreencast`), and `cv2.VideoWriter` turns them into a constant
frame rate mp4. Stdlib plus the OpenCV this project already has: no ffmpeg,
no OBS, no browser-automation package.

Four pieces, in the order a frame meets them:

- the client half of RFC 6455. `couch.py` already speaks the server half; a
  client has to mask what it sends and check the server's accept key, and
  that is all that is new here. Frames are read with `couch.read_frame`.
- `Cdp`: JSON-RPC over that socket. Every call carries an id and waits for
  the reply with that id; everything without an id is an event, handed to
  whoever asked for it. One socket to the browser, flattened sessions.
- `Pacer`: the browser sends a frame whenever the page repaints, which is
  roughly but never exactly 60 times a second. The file needs exactly `fps`
  frames per second of take, so each output slot shows the newest capture
  at or before its own time: a gap repeats the last capture, a burst drops
  the extras, and N seconds is exactly N * fps frames.
- `Recorder`: launches the browser, loads the scene, waits for it to boot,
  and captures from `begin()` until the take is long enough or `stop()`.
  Decoding and encoding run on two threads so the capture never waits on
  the encoder; the game loop is in another thread again and never waits on
  any of this.
"""

from __future__ import annotations

import base64
import json
import math
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .config import Config
from .couch import OP_CLOSE, OP_PING, OP_PONG, OP_TEXT, accept_key, apply_mask, encode_frame, read_frame

OP_CONTINUATION = 0x0
# A screencast frame is a few hundred KB of base64. Anything near this is a
# broken stream, not a picture.
MAX_CDP_MESSAGE = 1 << 27

PORTRAIT_SIZE = (1080, 1920)
LANDSCAPE_SIZE = (1920, 1080)


class RecordError(RuntimeError):
    """The take could not be made: no browser, no WebGL, a scene that would
    not boot. The message says which, in one line."""


def frame_size(portrait: bool) -> tuple[int, int]:
    """(width, height) of the file: 1080x1920 portrait, 1920x1080 landscape."""
    return PORTRAIT_SIZE if portrait else LANDSCAPE_SIZE


# ------------------------------------------------------ websocket, client ---


class HandshakeError(ConnectionError):
    pass


def client_key(nonce: bytes | None = None) -> str:
    """A `Sec-WebSocket-Key`: sixteen random bytes, base64. RFC 6455 4.1."""
    return base64.b64encode(os.urandom(16) if nonce is None else nonce).decode("ascii")


def handshake_request(host: str, port: int, path: str, key: str) -> bytes:
    """The opening GET of a WebSocket connection. No Origin header: the
    DevTools server only checks an origin a page sends, and this is not one."""
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ).encode("ascii")


def check_handshake(head: bytes, key: str) -> None:
    """Raise HandshakeError unless `head` is a 101 that upgrades to websocket
    with the accept value our key calls for."""
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0].split(" ", 2) if lines else []
    if len(status) < 2 or status[1] != "101":
        raise HandshakeError(f"the server did not switch protocols: {lines[0] if lines else '(nothing)'}")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    if headers.get("upgrade", "").lower() != "websocket":
        raise HandshakeError("the server's 101 did not upgrade to websocket")
    if headers.get("sec-websocket-accept") != accept_key(key):
        raise HandshakeError("the server's Sec-WebSocket-Accept does not match our key")


def encode_client_frame(payload: bytes, opcode: int = OP_TEXT, mask: bytes | None = None) -> bytes:
    """One masked client-to-server frame, FIN set. A client MUST mask every
    frame (RFC 6455 5.3) with a fresh four-byte key; tests pass the RFC's."""
    key = os.urandom(4) if mask is None else bytes(mask)
    if len(key) != 4:
        raise ValueError("a masking key is four bytes")
    masked = apply_mask(payload, key)
    # The server framer already has the three length forms; take its header
    # and set the mask bit.
    framed = encode_frame(masked, opcode)
    head = bytearray(framed[: len(framed) - len(masked)])
    head[1] |= 0x80
    return bytes(head) + key + masked


class WebSocketClient:
    """A connected client: `send_text` from any thread, `receive` from one.

    Built from a byte reader and a write function so the tests can drive it
    without a socket; `connect` makes one on a real socket.
    """

    def __init__(self, reader, write: Callable[[bytes], None], closer: Callable[[], None] | None = None) -> None:
        self.reader = reader
        self._write = write
        self._closer = closer
        self._lock = threading.Lock()
        self.closed = False

    def send(self, payload: bytes, opcode: int = OP_TEXT) -> None:
        framed = encode_client_frame(payload, opcode)
        with self._lock:
            self._write(framed)

    def send_text(self, text: str) -> None:
        self.send(text.encode("utf-8"), OP_TEXT)

    def receive(self) -> tuple[int, bytes] | None:
        """The next whole message, (opcode, payload), or None once the server
        has closed. Pings are answered here; fragments are joined."""
        kind: int | None = None
        parts: list[bytes] = []
        while True:
            frame = read_frame(self.reader, MAX_CDP_MESSAGE)
            if frame is None:
                return None
            fin, opcode, payload = frame
            if opcode == OP_PING:
                self.send(payload[:125], OP_PONG)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                return None
            if opcode == OP_CONTINUATION:
                if kind is None:
                    raise ValueError("a continuation frame with no message to continue")
            else:
                kind, parts = opcode, []
            parts.append(payload)
            if fin:
                return kind, b"".join(parts)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.send(b"", OP_CLOSE)
        except OSError:
            pass
        if self._closer is not None:
            self._closer()


def connect(url: str, timeout: float = 10.0) -> WebSocketClient:
    """Open `ws://host:port/path` and shake hands."""
    parts = urlsplit(url)
    if parts.scheme != "ws" or not parts.hostname:
        raise ValueError(f"not a ws:// url: {url}")
    host, port = parts.hostname, parts.port or 80
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    key = client_key()
    reader = sock.makefile("rb")
    try:
        sock.sendall(handshake_request(host, port, path, key))
        lines = []
        while True:
            line = reader.readline(65537)
            if not line:
                raise HandshakeError("the server hung up during the handshake")
            lines.append(line)
            if line in (b"\r\n", b"\n") or len(lines) > 100:
                break
        check_handshake(b"".join(lines), key)
    except BaseException:
        reader.close()
        sock.close()
        raise
    sock.settimeout(None)

    def closer() -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        reader.close()
        sock.close()

    return WebSocketClient(reader, sock.sendall, closer)


# -------------------------------------------------------------------- cdp ---


class CdpError(RuntimeError):
    pass


class _Waiter:
    __slots__ = ("event", "reply")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.reply: dict | None = None


class Cdp:
    """The DevTools protocol over one websocket.

    `call` sends `{"id", "method", "params", "sessionId"}` and blocks until
    the reply with that id arrives, whatever arrives in between. `send` is
    the same without waiting (the screencast ack). Events go to handlers
    registered with `on`, on the reader thread, so a handler must be quick.
    """

    def __init__(self, ws, start: bool = True) -> None:
        self.ws = ws
        self._lock = threading.Lock()
        self._next_id = 0
        self._pending: dict[int, _Waiter] = {}
        self._handlers: dict[str, list[Callable[[dict, str | None], None]]] = {}
        self.closed = threading.Event()
        self.handler_errors = 0
        self._thread = threading.Thread(target=self._read, name="cdp-read", daemon=True)
        if start:
            self._thread.start()

    def on(self, method: str, handler: Callable[[dict, str | None], None]) -> None:
        self._handlers.setdefault(method, []).append(handler)

    @staticmethod
    def message(ident: int, method: str, params: dict | None = None, session: str | None = None) -> str:
        body: dict = {"id": ident, "method": method, "params": params or {}}
        if session:
            body["sessionId"] = session
        return json.dumps(body)

    def _new_id(self, waiter: _Waiter | None) -> int:
        with self._lock:
            if self.closed.is_set():
                raise CdpError("the browser connection is closed")
            self._next_id += 1
            if waiter is not None:
                self._pending[self._next_id] = waiter
            return self._next_id

    def send(self, method: str, params: dict | None = None, session: str | None = None) -> int:
        ident = self._new_id(None)
        self.ws.send_text(self.message(ident, method, params, session))
        return ident

    def call(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 30.0) -> dict:
        waiter = _Waiter()
        ident = self._new_id(waiter)
        try:
            self.ws.send_text(self.message(ident, method, params, session))
        except OSError as error:
            with self._lock:
                self._pending.pop(ident, None)
            raise CdpError(f"{method}: could not send ({error})") from error
        if not waiter.event.wait(timeout):
            with self._lock:
                self._pending.pop(ident, None)
            raise CdpError(f"{method}: no reply in {timeout:g} s")
        reply = waiter.reply
        if reply is None:
            raise CdpError(f"{method}: the browser connection closed before it replied")
        if "error" in reply:
            error = reply["error"] or {}
            raise CdpError(f"{method}: {error.get('message', error)} {error.get('data', '')}".strip())
        return reply.get("result") or {}

    def dispatch(self, message: dict) -> None:
        """One decoded message from the browser: a reply or an event."""
        ident = message.get("id")
        if ident is not None:
            with self._lock:
                waiter = self._pending.pop(ident, None)
            if waiter is not None:
                waiter.reply = message
                waiter.event.set()
            return
        for handler in self._handlers.get(message.get("method", ""), ()):
            try:
                handler(message.get("params") or {}, message.get("sessionId"))
            except Exception:  # a broken handler must not take the socket down
                self.handler_errors += 1

    def _read(self) -> None:
        try:
            while True:
                received = self.ws.receive()
                if received is None:
                    break
                opcode, payload = received
                if opcode != OP_TEXT:
                    continue
                try:
                    message = json.loads(payload)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    self.dispatch(message)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                self.closed.set()
                waiting = list(self._pending.values())
                self._pending.clear()
            for waiter in waiting:
                waiter.event.set()

    def close(self) -> None:
        try:
            self.ws.close()
        except OSError:
            pass
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)


# ------------------------------------------------------------------ pacing ---


class Pacer:
    """Timestamps in, output slots out.

    Slot k of the file is `start + k / fps`, `start` being the first
    capture's timestamp. Each capture takes the next free slot, unless it is
    more than `LATE` slots past it (a real gap: the slots in between repeat
    the previous capture and it takes its own slot) or more than `EARLY`
    slots before it (the output is running ahead of the captures: it
    replaces the current capture, which is dropped). So a gap repeats,
    extras drop, the picture is never more than about one slot off its real
    time, and with `seconds` the file is exactly `round(seconds * fps)`
    slots; `done` says when they are all spoken for.

    Why not simply "the newest capture before each slot's time": the
    screencast's timestamps wobble by up to half a frame either way (27 ms
    then 10 ms is common under load here, median 16.2 ms), and a fixed grid
    turns every wobble across a slot boundary into a dropped frame next to a
    repeated one. Measured on a 10 s take: 487 distinct frames in 600 slots
    from 581 captures with the grid.
    """

    LATE = 1.0
    EARLY = 1.0

    def __init__(self, fps: float, seconds: float | None = None) -> None:
        if fps <= 0:
            raise ValueError("fps must be positive")
        self.fps = float(fps)
        self.total = None if seconds is None else max(1, round(seconds * fps))
        self.start: float | None = None
        self.slot = 0  # the slot the current capture starts in
        self.written = 0  # slots given out, always equal to `slot`
        self._pending = False  # there is a current capture

    @property
    def done(self) -> bool:
        return self.total is not None and self.slot >= self.total

    def push(self, timestamp: float) -> int:
        """A capture arrived. Returns how many slots the PREVIOUS capture fills
        (0 when this one replaces it); this one becomes the current capture."""
        if self.start is None:
            self.start = timestamp
            self._pending = True
            return 0
        if self.done:
            return 0
        position = (timestamp - self.start) * self.fps
        following = self.slot + 1
        # The 1e-6 keeps float noise off the boundaries: a capture exactly one
        # slot late (a steady 30 fps) is late, not on time.
        if position < following - self.EARLY - 1e-6:
            return 0
        slot = following if position < following + self.LATE - 1e-6 else round(position)
        if self.total is not None:
            slot = min(slot, self.total)
        count = slot - self.slot
        self.slot = slot
        self.written = slot
        return count

    def finish(self, fill: bool = True) -> int:
        """Slots for the last capture. With `fill` and a length, every slot
        left; otherwise the one it is in (a take stopped early ends on the
        last thing it saw)."""
        if not self._pending:
            return 0
        if fill and self.total is not None:
            count = max(0, self.total - self.slot)
        else:
            count = 1 if (self.total is None or self.slot < self.total) else 0
        self.slot += count
        self.written = self.slot
        self._pending = False
        return count


def frame_indices(timestamps, fps: float, seconds: float | None = None) -> list[int]:
    """The pacer as a pure function: capture timestamps in, and for each
    output frame the index of the capture it shows."""
    pacer = Pacer(fps, seconds)
    out: list[int] = []
    current: int | None = None
    for index, stamp in enumerate(timestamps):
        if pacer.done:
            break
        count = pacer.push(float(stamp))
        if count and current is not None:
            out.extend([current] * count)
        current = index
    if current is not None:
        out.extend([current] * pacer.finish())
    return out


# ----------------------------------------------------------------- browser ---

BROWSER_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
)
BROWSER_NAMES = ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")

# Every launch. `--remote-debugging-port=0` lets the browser pick a free port
# and write it to DevToolsActivePort in the profile, so there is no race
# between choosing a port and binding it.
BASE_FLAGS = (
    "--headless=new",
    "--disable-gpu-vsync",
    "--hide-scrollbars",
    "--autoplay-policy=no-user-gesture-required",
    "--remote-debugging-port=0",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-sync",
    "--mute-audio",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
)
# The WebGL paths, tried in order until the scene boots: the real GPU through
# ANGLE, then SwiftShader on the CPU. Which one ran goes in the result.
WEBGL_PATHS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gpu", ("--use-angle=default", "--ignore-gpu-blocklist")),
    ("swiftshader", ("--use-angle=swiftshader", "--enable-unsafe-swiftshader")),
)


def find_browser(override: str | Path | None = None) -> Path | None:
    """Edge or Chrome, whichever is here. `override` is taken as given."""
    if override:
        path = Path(os.path.expandvars(str(override)))
        return path if path.is_file() else None
    for candidate in BROWSER_PATHS:
        path = Path(os.path.expandvars(candidate))
        if path.is_file():
            return path
    for name in BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


class Browser:
    """One headless browser process with its own throwaway profile."""

    def __init__(self, executable: Path, flags: tuple[str, ...], size: tuple[int, int], timeout: float = 20.0) -> None:
        self.executable = Path(executable)
        self.flags = (*BASE_FLAGS, *flags)
        self.profile = Path(tempfile.mkdtemp(prefix="flybrain-record-"))
        width, height = size
        command = [
            str(self.executable),
            *self.flags,
            f"--window-size={width},{height}",
            f"--user-data-dir={self.profile}",
            "about:blank",
        ]
        windows = sys.platform == "win32"
        # Its own process group, so the Ctrl+C that stops the run finishes the
        # file instead of killing the browser under it.
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0,
            start_new_session=not windows,
        )
        try:
            self.ws_url = self._endpoint(timeout)
        except BaseException:
            self.close()
            raise

    def _endpoint(self, timeout: float) -> str:
        port_file = self.profile / "DevToolsActivePort"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code = self.process.poll()
            if code is not None:
                raise RecordError(f"{self.executable.name} exited with code {code} before opening its debugging port")
            try:
                words = port_file.read_text(encoding="ascii").split()
            except OSError:
                words = []
            if len(words) >= 2:
                return f"ws://127.0.0.1:{words[0]}{words[1]}"
            time.sleep(0.05)
        raise RecordError(f"{self.executable.name} did not open a debugging port within {timeout:g} s")

    def close(self, cdp: Cdp | None = None) -> None:
        if cdp is not None and not cdp.closed.is_set():
            try:
                cdp.call("Browser.close", timeout=3.0)
            except CdpError:
                pass  # it usually hangs up before it answers
        try:
            self.process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                # The whole tree, and only this tree: our own browser's pid.
                subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                self.process.kill()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
        for _ in range(40):
            try:
                shutil.rmtree(self.profile)
                break
            except FileNotFoundError:
                break
            except OSError:
                time.sleep(0.25)  # a child process still has a file open


# ---------------------------------------------------------------- recorder ---

# Evaluated in the page once it has booted: which GPU WebGL landed on.
RENDERER_PROBE = """(() => {
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
  if (!gl) return '';
  const info = gl.getExtension('WEBGL_debug_renderer_info');
  return String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
})()"""

# How fast the page draws on its own, over one second, before the take.
PAGE_FPS_PROBE = """new Promise((resolve) => {
  let frames = 0;
  let first = 0;
  function tick(now) {
    if (!first) first = now;
    else frames += 1;
    if (now - first >= 1000) resolve(frames * 1000 / (now - first));
    else requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})"""

BOOT_PROBE = """JSON.stringify({
  booted: window.__couchBooted === true,
  crash: (document.getElementById('crash-text') || {}).textContent || ''
})"""


@dataclass
class RecordResult:
    path: Path
    fps: int = 60
    size: tuple[int, int] = PORTRAIT_SIZE
    frames: int = 0  # frames in the file
    captured: int = 0  # screencast frames the browser sent during the take
    used: int = 0  # of those, how many are in the file at least once
    dropped: int = 0  # captures lost because the encoder's backlog was full
    resized: int = 0  # captures that came at another size and were scaled
    webgl: str = ""  # which WebGL path ran: "gpu" or "swiftshader"
    renderer: str = ""  # the WebGL renderer string the page saw
    page_fps: float = 0.0  # the page's own draw rate before the take
    wall: float = 0.0  # seconds from launch to a closed file
    catch_up: float = 0.0  # seconds from the end of the take to a closed file
    early: bool = False  # stopped before the take was long enough
    error: str | None = None
    min_fps: float = 50.0
    stamps: list[float] = field(default_factory=list)  # capture timestamps, for diagnostics

    @property
    def seconds(self) -> float:
        return self.frames / self.fps if self.fps else 0.0

    @property
    def capture_fps(self) -> float:
        return self.captured / self.seconds if self.seconds else 0.0

    @property
    def slow(self) -> bool:
        return self.frames > 0 and self.capture_fps < self.min_fps

    def line(self) -> str:
        width, height = self.size
        text = (
            f"{self.path}: {self.seconds:.2f} s, {self.frames} frames at {self.fps} fps, {width}x{height}; "
            f"captured {self.captured} frames from the browser = {self.capture_fps:.1f} fps "
            f"({self.used} used, {self.dropped} dropped); WebGL {self.webgl or '?'} ({self.renderer or '?'}), "
            f"page drew {self.page_fps:.0f} fps before the take; {self.wall:.1f} s wall clock "
            f"({self.catch_up:.1f} s of it encoding after the take)"
        )
        if self.early:
            text += "; stopped early"
        if self.error:
            text += f"; ERROR: {self.error}"
        return text

    def warning(self) -> str | None:
        if not self.slow:
            return None
        return (
            f"WARNING: CAPTURE RATE {self.capture_fps:.1f} FPS IS UNDER {self.min_fps:g}. {self.path} is a "
            f"{self.fps} fps file made of {self.capture_fps:.0f} captures a second, so it will stutter."
        )


class Recorder:
    """One take. `start()` launches the browser in a thread and loads the
    scene; `wait_ready()` blocks until frames are flowing; `begin()` starts
    the clock. The take ends when it is `seconds` long, `stop()` is called,
    or the browser goes away, and `take_over` is set then: that is what the
    game loop stops on. The encoder may still be catching up; `finished` is
    set once the file is closed, and `join()` returns the RecordResult.
    """

    def __init__(
        self,
        cfg: Config,
        url: str,
        out: str | Path,
        seconds: float,
        *,
        fps: int | None = None,
        size: tuple[int, int] = PORTRAIT_SIZE,
        browser: str | Path | None = None,
        say: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.url = url
        self.out = Path(out)
        self.seconds = float(seconds)
        self.fps = int(fps or cfg.couch_record_fps)
        self.size = (int(size[0]), int(size[1]))
        self.browser_path = browser
        self.say = say or (lambda line: print(line, flush=True))
        self.ready = threading.Event()
        self.take_over = threading.Event()  # the take is long enough (or stopped)
        self.finished = threading.Event()  # and the file is closed
        self._begun = threading.Event()
        self._stop = threading.Event()
        self._begin_at = math.inf
        self._frames: queue.Queue[tuple[float, str]] = queue.Queue(maxsize=max(1, cfg.couch_record_backlog))
        self.result = RecordResult(path=self.out, fps=self.fps, size=self.size, min_fps=cfg.couch_record_min_fps)
        self.cdp: Cdp | None = None
        self.session: str | None = None
        self._browser: Browser | None = None
        self._thread: threading.Thread | None = None
        self._started = 0.0

    # -- the caller's side ---------------------------------------------------

    def start(self) -> Recorder:
        self._started = time.perf_counter()
        self._thread = threading.Thread(target=self._run, name="record", daemon=True)
        self._thread.start()
        return self

    def wait_ready(self, timeout: float | None = None) -> None:
        """Block until the scene is up and the screencast is running. Raises
        RecordError when the recorder gave up, or after `timeout` seconds."""
        limit = self.cfg.couch_record_ready_timeout if timeout is None else timeout
        deadline = time.monotonic() + limit
        while not self.ready.wait(0.1):
            if self.finished.is_set():
                raise RecordError(self.result.error or "the recorder stopped before the scene was ready")
            if time.monotonic() > deadline:
                self.stop()
                raise RecordError(f"the scene was not ready in the browser after {limit:g} s")

    def begin(self) -> None:
        """The take starts with the first capture from now on."""
        self._begin_at = time.time()
        self._begun.set()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> RecordResult:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.result

    # -- the browser's side ----------------------------------------------------

    def on_frame(self, params: dict, session: str | None) -> None:
        """A `Page.screencastFrame`, on the CDP reader thread. Acknowledged at
        once, whatever happens to it: the browser holds the next frame back
        until this one is acked, and waiting for the encoder would pace the
        capture by the encoder."""
        cdp = self.cdp
        if cdp is not None:
            try:
                cdp.send("Page.screencastFrameAck", {"sessionId": params.get("sessionId")}, session)
            except (OSError, CdpError):
                pass
        if not self._begun.is_set() or self.take_over.is_set():
            return
        metadata = params.get("metadata") or {}
        stamp = float(metadata.get("timestamp") or time.time())
        if stamp < self._begin_at:
            return
        try:
            self._frames.put_nowait((stamp, params.get("data") or ""))
        except queue.Full:
            self.result.dropped += 1

    # -- the recorder's thread -------------------------------------------------

    def _run(self) -> None:
        try:
            self._open()
            self.ready.set()
            self._capture()
        except Exception as error:  # everything ends up in the result
            self.result.error = str(error) or type(error).__name__
        finally:
            self.take_over.set()
            self._close()
            self.result.wall = time.perf_counter() - self._started
            self.finished.set()

    def _open(self) -> None:
        executable = find_browser(self.browser_path)
        if executable is None:
            where = self.browser_path or "Edge or Chrome in the usual places"
            raise RecordError(f"no browser found ({where}); pass --browser PATH")
        failures = []
        for name, flags in WEBGL_PATHS:
            if self._stop.is_set():
                raise RecordError("stopped before the browser was ready")
            browser = None
            cdp = None
            try:
                browser = Browser(executable, flags, self.size)
                cdp = Cdp(connect(browser.ws_url))
                self.cdp = cdp
                self.session = self._open_page(cdp)
                self.result.renderer = self._boot(cdp, self.session)
            except (RecordError, CdpError, OSError, ValueError) as error:
                failures.append(f"{name}: {error}")
                self.say(f"record: the {name} WebGL path did not start the scene ({error})")
                if browser is not None:
                    browser.close(cdp)
                if cdp is not None:
                    cdp.close()
                self.cdp = None
                continue
            self._browser = browser
            # Chrome can fall back to SwiftShader on its own; say so if it did.
            software = "swiftshader" in self.result.renderer.lower() and name != "swiftshader"
            self.result.webgl = f"{name}, but on SwiftShader" if software else name
            break
        else:
            raise RecordError(f"the scene would not start in headless {executable.name}: " + "; ".join(failures))
        try:
            probe = cdp.call(
                "Runtime.evaluate",
                {"expression": PAGE_FPS_PROBE, "awaitPromise": True, "returnByValue": True},
                self.session,
                timeout=10.0,
            )
            self.result.page_fps = float(probe.get("result", {}).get("value") or 0.0)
        except (CdpError, TypeError, ValueError):
            self.result.page_fps = 0.0
        cdp.on("Page.screencastFrame", self.on_frame)
        width, height = self.size
        cdp.call(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": int(self.cfg.couch_record_quality),
                "maxWidth": width,
                "maxHeight": height,
                "everyNthFrame": 1,
            },
            self.session,
        )

    def _open_page(self, cdp: Cdp) -> str:
        """Attach to the browser's page (flattened session), set the viewport
        to exactly the file's size at DPR 1, and load the scene."""
        targets = cdp.call("Target.getTargets").get("targetInfos", [])
        pages = [target for target in targets if target.get("type") == "page"]
        if pages:
            target = pages[0]["targetId"]
        else:
            target = cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = cdp.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        width, height = self.size
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": 1,
                "mobile": False,
                "screenWidth": width,
                "screenHeight": height,
            },
            session,
        )
        cdp.call("Page.enable", session=session)
        cdp.call("Page.navigate", {"url": self.url}, session)
        return session

    def _boot(self, cdp: Cdp, session: str) -> str:
        """Wait for main.js to say it booted, and name the WebGL renderer.
        The page's own crash box (index.html) is read out if it shows."""
        deadline = time.monotonic() + self.cfg.couch_record_ready_timeout
        while time.monotonic() < deadline:
            if self._stop.is_set():
                raise RecordError("stopped before the scene booted")
            reply = cdp.call(
                "Runtime.evaluate", {"expression": BOOT_PROBE, "returnByValue": True}, session, timeout=10.0
            )
            try:
                state = json.loads(reply.get("result", {}).get("value") or "{}")
            except ValueError:
                state = {}
            if state.get("crash"):
                raise RecordError("the scene crashed: " + " ".join(state["crash"].split())[:300])
            if state.get("booted"):
                probe = cdp.call(
                    "Runtime.evaluate", {"expression": RENDERER_PROBE, "returnByValue": True}, session, timeout=10.0
                )
                renderer = str(probe.get("result", {}).get("value") or "")
                if not renderer:
                    raise RecordError("the scene booted but WebGL is unavailable")
                return renderer
            time.sleep(0.1)
        raise RecordError("the scene did not boot")

    def _capture(self) -> None:
        """The take, in three stages on three threads, so nothing that is
        slow can hold the capture up:

        - here: each capture's JPEG is appended to a spool file as it comes
          and the pacer decides which slots it fills. When the take is long
          enough `take_over` is set (the game loop ends on it), the browser
          is shut, and the rest is catching up.
        - a decoder: JPEG to pixels, only for captures the file uses.
        - an encoder: pixels into the mp4, each as many times as the pacer
          said. cv2 lets go of the GIL in both, so they overlap each other.

        Measured here with the browser and the game on the same CPU, the
        two together manage about 37 frames a second at 1080x1920, under
        the 60 a take arrives at; without the spool the backlog would sit in
        memory and a 30 s take would lose frames. With it, the file just
        finishes a little after the take does.
        """
        import cv2
        import numpy as np

        width, height = self.size
        self.out.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(self.out), cv2.VideoWriter_fourcc(*"mp4v"), float(self.fps), (width, height))
        if not writer.isOpened():
            raise RecordError(f"cv2.VideoWriter could not open {self.out} for mp4v")
        spool = tempfile.TemporaryFile(prefix="flybrain-take-")
        spool_lock = threading.Lock()
        plan: queue.Queue = queue.Queue()  # (offset, length, count), then None
        decoded: queue.Queue = queue.Queue(maxsize=8)  # (pixels, count), then None
        failed: list[str] = []

        def decoder() -> None:
            try:
                while True:
                    item = plan.get()
                    if item is None:
                        return
                    offset, length, count = item
                    with spool_lock:
                        spool.seek(offset)
                        data = spool.read(length)
                    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR) if data else None
                    if image is None:
                        image = np.zeros((height, width, 3), dtype=np.uint8)
                        failed.append("a capture that is not a JPEG")
                    if image.shape[0] != height or image.shape[1] != width:
                        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
                        self.result.resized += 1
                    self.result.used += 1
                    decoded.put((image, count))
            finally:
                decoded.put(None)

        def encoder() -> None:
            while True:
                item = decoded.get()
                if item is None:
                    return
                image, count = item
                try:
                    for _ in range(count):
                        writer.write(image)
                except cv2.error as error:
                    failed.append(str(error))

        threads = [
            threading.Thread(target=decoder, name="record-decode", daemon=True),
            threading.Thread(target=encoder, name="record-encode", daemon=True),
        ]
        for thread in threads:
            thread.start()

        def spooled(data: str) -> tuple[int, int]:
            raw = base64.b64decode(data)
            with spool_lock:
                spool.seek(0, os.SEEK_END)
                offset = spool.tell()
                spool.write(raw)
            return offset, len(raw)

        pacer = Pacer(self.fps, self.seconds)
        current: tuple[int, int] | None = None
        wall_end = math.inf
        early = False
        try:
            while not self._begun.wait(0.1):
                if self._stop.is_set():
                    early = True
                    break
            while not early:
                if self._stop.is_set():
                    early = True
                    break
                try:
                    stamp, data = self._frames.get(timeout=0.1)
                except queue.Empty:
                    if self.cdp is None or self.cdp.closed.is_set():
                        early = True
                        self.result.error = "the browser went away during the take"
                        break
                    if time.time() > wall_end:
                        break  # the page stopped repainting: the last frame holds to the end
                    continue
                if pacer.start is None:
                    wall_end = time.time() + self.seconds + self.cfg.couch_record_stall
                count = pacer.push(stamp)
                if current is not None and count:
                    plan.put((*current, count))
                if pacer.done:
                    break
                current = spooled(data)
                self.result.captured += 1
                self.result.stamps.append(stamp)
            if current is not None:
                count = pacer.finish(fill=not early)
                if count:
                    plan.put((*current, count))
        finally:
            plan.put(None)
            self.result.frames = pacer.written
            self.result.early = early
            self.take_over.set()
            took = time.perf_counter()
            # The browser is done: give its CPU to the encoder.
            self._close()
            for thread in threads:
                thread.join()
            writer.release()
            spool.close()
            self.result.catch_up = time.perf_counter() - took
            if failed:
                self.result.error = f"the encoder failed: {failed[0]}"

    def _close(self) -> None:
        """Stop the screencast and shut the browser. Safe to call twice."""
        cdp = self.cdp
        if cdp is not None and self.session and not cdp.closed.is_set():
            try:
                cdp.call("Page.stopScreencast", session=self.session, timeout=3.0)
            except CdpError:
                pass
        if self._browser is not None:
            self._browser.close(cdp)
            self._browser = None
        if cdp is not None:
            cdp.close()


def record(
    cfg: Config,
    url: str,
    out: str | Path,
    seconds: float,
    *,
    fps: int | None = None,
    size: tuple[int, int] = PORTRAIT_SIZE,
    browser: str | Path | None = None,
    say: Callable[[str], None] | None = None,
) -> RecordResult:
    """Record `seconds` of the page at `url` into `out`, blocking. The page
    has to be served already (a running couch server). Ctrl+C finishes the
    file where it is and returns."""
    recorder = Recorder(cfg, url, out, seconds, fps=fps, size=size, browser=browser, say=say).start()
    try:
        recorder.wait_ready()
        recorder.begin()
        while not recorder.finished.wait(0.2):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        recorder.stop()
        result = recorder.join()
    return result
