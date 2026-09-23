"""The couch scene's server, its observer, and a syntax check on the scene.

Nothing here needs a ROM, a browser or a GPU. The websocket client at the
bottom of this file is forty lines of `socket`, so the "a real client connects"
test really is a real client rather than a mock of one.
"""

import base64
import io
import json
import math
import shutil
import socket
import subprocess
import time
from dataclasses import replace

import numpy as np
import pytest
from conftest import ROOT

from flybrain.config import POOL_NAMES, Config
from flybrain.connectome import synthetic
from flybrain.couch import (
    OP_BINARY,
    OP_TEXT,
    VIDEO_MESSAGE,
    CouchServer,
    Hub,
    accept_key,
    encode_frame,
    read_client_frame,
)
from flybrain.couch_observer import FRAME_HEIGHT, FRAME_WIDTH, CouchObserver, SpikeSampler
from flybrain.loop import TickState
from flybrain.reward import PARTS

VIDEO_BYTES = 1 + FRAME_WIDTH * FRAME_HEIGHT  # the contract's 23,041


def fast_config(**extra):
    """A server that gives up on a stalled client quickly, so the drop test
    takes a second rather than the several a real run allows."""
    return replace(
        Config(),
        couch_send_timeout=0.3,
        couch_wait=0.03,
        couch_state_hz=1000.0,
        couch_video_fps=1000.0,
        **extra,
    )


def a_tick(step=1, started=(), action=None, panic=False, value=7.0):
    return TickState(
        step=step,
        frame=np.full((FRAME_HEIGHT, FRAME_WIDTH), step % 251, dtype=np.uint8),
        pressed=("UP",),
        started=tuple(started),
        action=action,
        excursion=np.arange(7, dtype=np.float32),
        firing_rate=0.0871,
        dopamine=-0.25,
        value=value,
        mbon=np.linspace(-1, 1, 7).astype(np.float32),
        reward=0.0,
        reward_parts=dict.fromkeys(PARTS, 0.0),
        episode_reward=131.0,
        map_id=0x26,
        map_name="Red's house 2F",
        x=3,
        y=4,
        in_battle=False,
        panic=panic,
        panics=2,
    )


def payload_of(framed):
    """The bytes inside a frame. Not `framed[2:]`: the length form varies, and
    a length byte can perfectly well be an opening brace."""
    return read_client_frame(io.BytesIO(framed))[1]


def state_in(hub):
    return json.loads(payload_of(hub.latest("state")))


@pytest.fixture
def server():
    made = CouchServer(fast_config(), port=0).start()
    try:
        yield made
    finally:
        made.stop()


# ------------------------------------------------------------- framing -----


def test_the_accept_key_matches_the_rfc_worked_example():
    """RFC 6455 section 1.3. Get this wrong and no browser will ever connect."""
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


@pytest.mark.parametrize(("size", "header"), [(0, 2), (125, 2), (126, 4), (65535, 4), (65536, 10)])
def test_a_frame_uses_the_right_length_form(size, header):
    framed = encode_frame(b"x" * size, OP_BINARY)
    assert len(framed) == header + size
    assert framed[0] == 0x80 | OP_BINARY
    if header == 2:
        assert framed[1] == size
    elif header == 4:
        assert framed[1] == 126 and int.from_bytes(framed[2:4], "big") == size
    else:
        assert framed[1] == 127 and int.from_bytes(framed[2:10], "big") == size
    assert framed[header:] == b"x" * size


@pytest.mark.parametrize("size", [0, 125, 126, 65535, 65536])
def test_a_frame_reads_back_the_way_it_was_written(size):
    body = (bytes(range(256)) * (size // 256 + 1))[:size]
    opcode, back = read_client_frame(io.BytesIO(encode_frame(body, OP_TEXT)))
    assert opcode == OP_TEXT and back == body


# ------------------------------------------------------- static serving -----


def http_get(server, path):
    """A raw request, because urllib would normalise `..` away before it left."""
    with socket.create_connection((server.host, server.port), timeout=5.0) as sock:
        sock.sendall(f"GET {path} HTTP/1.1\r\nHost: couch\r\nConnection: close\r\n\r\n".encode("ascii"))
        chunks = []
        while True:
            block = sock.recv(65536)
            if not block:
                break
            chunks.append(block)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    return int(head.split()[1]), body


def test_the_page_and_its_modules_are_served(server):
    status, body = http_get(server, "/")
    assert status == 200 and b'id="stage"' in body
    for path in ("/js/main.js", "/js/net.js", "/vendor/three.module.js", "/vendor/three.core.js"):
        code, content = http_get(server, path)
        assert code == 200 and content, path


def test_nothing_outside_the_scene_folder_is_served(server):
    for path in ("/../run.py", "/%2e%2e/run.py", "/../../windows/win.ini", "/js/../../run.py"):
        status, _ = http_get(server, path)
        assert status == 403, path


def test_an_unknown_path_is_a_404(server):
    assert http_get(server, "/js/nothing-here.js")[0] == 404


def test_the_websocket_path_refuses_a_plain_get(server):
    assert http_get(server, "/ws")[0] == 400


# ------------------------------------------------------------ the feed -----


def test_a_real_client_gets_the_hello_the_state_and_a_video_frame(server):
    watcher = CouchObserver(server.cfg, server.hub)
    client = WsClient(server.host, server.port)
    assert "101 Switching Protocols" in client.head
    assert f"Sec-WebSocket-Accept: {accept_key(client.key)}" in client.head

    watcher(a_tick(step=5))

    seen = {}
    for _ in range(3):
        opcode, body = client.recv()
        if opcode == OP_BINARY:
            seen["video"] = body
        else:
            message = json.loads(body)
            seen[message["type"]] = message
    client.close()

    assert set(seen) == {"hello", "state", "video"}
    assert len(seen["video"]) == VIDEO_BYTES
    assert seen["video"][0] == VIDEO_MESSAGE
    assert set(seen["video"][1:]) == {5}
    assert seen["hello"]["pools"] == list(POOL_NAMES)
    assert seen["state"]["step"] == 5
    assert seen["state"]["map_name"] == "Red's house 2F"
    assert seen["state"]["episode_reward"] == 131.0


def test_a_client_that_stops_reading_is_dropped_and_the_loop_is_never_held_up(server):
    watcher = CouchObserver(server.cfg, server.hub)
    client = WsClient(server.host, server.port)  # connects, then never reads
    assert wait_for(lambda: server.hub.clients == 1), "the server never registered the client"

    tick = a_tick(step=1)
    durations = []
    end = time.monotonic() + 20.0
    while server.hub.clients and time.monotonic() < end:
        at = time.perf_counter()
        watcher(tick)
        durations.append(time.perf_counter() - at)
        time.sleep(0.001)
    client.close()

    assert server.hub.clients == 0, "a client that stopped reading was not dropped"
    assert server.hub.clients_dropped == 1
    # The observer runs inside the game loop, so what matters is that it never
    # waits on a socket. This machine has a training run on it, so the claim is
    # about the typical call and not a worst case the scheduler owns.
    ordered = sorted(durations)
    median = ordered[len(ordered) // 2]
    assert median < 1.0e-3, f"median observer call was {median * 1000:.3f} ms over {len(durations)} calls"


def test_the_port_is_released_when_the_server_stops():
    made = CouchServer(Config(), port=0).start()
    host, port = made.host, made.port
    with socket.create_connection((host, port), timeout=2.0):
        pass
    made.stop()

    with pytest.raises(OSError):
        socket.create_connection((host, port), timeout=1.0).close()
    again = socket.socket()
    try:
        again.bind((host, port))
        again.listen(1)
    finally:
        again.close()


# ------------------------------------------------------- the observer ------


def test_the_spike_sample_is_256_bits_from_every_pool_and_the_rest_of_the_net():
    cfg = Config()
    connectome = synthetic(n=2000, seed=0, cfg=cfg)
    sampler = SpikeSampler(connectome, cfg)

    assert sampler.size == cfg.couch_spike_sample
    assert len(sampler.labels) == cfg.couch_spike_sample
    assert len(sampler.pack(np.zeros(connectome.n, dtype=bool))) == cfg.couch_spike_sample // 8
    for name in POOL_NAMES:
        picked = [int(i) for i, label in zip(sampler.indices, sampler.labels) if label == name]
        assert len(picked) == cfg.couch_spike_per_pool
        assert set(picked) <= {int(i) for i in connectome.motor_pools[name]}
    hidden = [int(i) for i, label in zip(sampler.indices, sampler.labels) if not label]
    assert len(hidden) == cfg.couch_spike_sample - cfg.couch_spike_per_pool * len(POOL_NAMES)
    assert not set(hidden) & {int(i) for i in connectome.motor_idx}


def test_the_spike_sample_is_the_same_neurons_under_the_same_seed():
    cfg = Config()
    connectome = synthetic(n=2000, seed=0, cfg=cfg)
    first = SpikeSampler(connectome, cfg)
    second = SpikeSampler(connectome, cfg)
    other = SpikeSampler(connectome, replace(cfg, seed=cfg.seed + 1))
    assert np.array_equal(first.indices, second.indices)
    assert not np.array_equal(first.indices, other.indices)


def test_packed_bits_say_which_neurons_spiked():
    cfg = Config()
    connectome = synthetic(n=2000, seed=0, cfg=cfg)
    sampler = SpikeSampler(connectome, cfg)
    spikes = np.zeros(connectome.n, dtype=bool)
    spikes[sampler.indices[0]] = True
    spikes[sampler.indices[9]] = True
    bits = np.unpackbits(np.frombuffer(sampler.pack(spikes), dtype=np.uint8))
    assert list(np.flatnonzero(bits)) == [0, 9]


def test_a_press_that_starts_and_ends_between_two_sends_still_reaches_the_scene():
    """A press is four ticks long and state messages are twenty milliseconds
    apart, so the held set alone loses presses. The events list must not."""
    cfg = replace(Config(), couch_state_hz=0.5, couch_video_fps=0.5)
    hub = Hub()
    watcher = CouchObserver(cfg, hub)
    for step in range(1, 9):
        pressed = step == 3
        watcher(a_tick(step=step, started=("A",) if pressed else (), action="A" if pressed else None))
    # The first tick always flushes, so a client that connects late still has
    # something to draw. After that, half a message a second sends nothing.
    assert state_in(hub)["step"] == 1

    watcher.state_ticker.reset()  # force the next tick to flush
    watcher(a_tick(step=9))
    state = state_in(hub)
    assert [(e["step"], e["pool"]) for e in state["events"]] == [(3, "A")]
    assert state["history"] == ["A"]
    assert state["pressed"] == ["UP"]

    watcher.state_ticker.reset()
    watcher(a_tick(step=10))
    assert state_in(hub)["events"] == [], "the same press was sent twice"


def test_the_send_rate_holds_its_average_against_a_coarser_tick_clock():
    """The naive gate fires every other tick at 60 Hz, which turns 45 messages
    a second into 30. Measured on a real run before `Ticker` existed."""
    from flybrain.couch_observer import Ticker

    for hz, ticks_per_second in ((45.0, 60.0), (30.0, 60.0), (45.0, 1400.0)):
        ticker = Ticker(hz)
        step = 1.0 / ticks_per_second
        seconds = 10.0
        for i in range(int(seconds * ticks_per_second)):
            ticker.ready(i * step)
        assert abs(ticker.count / seconds - hz) < 1.0, (hz, ticks_per_second, ticker.count)


def test_a_stalled_gate_does_not_fire_a_burst_to_catch_up():
    from flybrain.couch_observer import Ticker

    ticker = Ticker(30.0)
    ticker.ready(0.0)
    before = ticker.count
    for i in range(20):  # twenty ticks crammed into one millisecond after a 5 s stall
        ticker.ready(5.0 + i * 0.00005)
    assert ticker.count - before == 1


def test_the_state_message_never_carries_a_nan():
    hub = Hub()
    watcher = CouchObserver(fast_config(), hub)
    watcher(a_tick(step=1, value=math.nan))
    text = payload_of(hub.latest("state")).decode("utf-8")
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text)["value"] == 0.0


class FakeFly:
    """What `attach` actually needs: a connectome, a brain and a motor."""

    def __init__(self):
        self.connectome = synthetic(n=2000, seed=0, cfg=Config())
        self.brain = type("Brain", (), {"spikes": np.zeros(2000, dtype=bool)})()
        self.motor = type("Motor", (), {"panicked": []})()


def test_the_observer_takes_the_fly_and_the_raster_fills_in():
    """`run_loop` calls `attach` on any observer that has one. Without it the
    raster has nothing to draw, so this is the wiring that matters."""
    hub = Hub()
    watcher = CouchObserver(fast_config(), hub)
    assert watcher.sampler is None
    assert json.loads(payload_of(hub.latest("hello")))["spike_bits"] == 0

    fly = FakeFly()
    fly.brain.spikes[fly.connectome.motor_pools["UP"][0]] = True
    watcher.attach(fly)
    watcher(a_tick(step=1))

    state = state_in(hub)
    assert state["spikes"] and len(base64.b64decode(state["spikes"])) == 32
    hello = json.loads(payload_of(hub.latest("hello")))
    assert hello["spike_bits"] == 256
    assert set(hello["spike_labels"]) == set(POOL_NAMES) | {""}


def test_run_loop_offers_the_fly_to_an_observer_that_asks_for_it():
    """Checked without a ROM by reading the hook itself: `run_loop` calls
    `attach(fly)` on every watcher that has one, right where it sets `title`."""
    import inspect

    from flybrain.loop import run_loop

    source = inspect.getsource(run_loop)
    assert 'getattr(watcher, "attach", None)' in source and "attach(fly)" in source


# ---------------------------------------------------------- the scene ------


NODE = shutil.which("node")
SCENE = ROOT / "scene"


def test_the_scene_has_the_files_the_page_asks_for():
    for name in (
        "index.html",
        "PROTOCOL.md",
        "REVIEW.md",
        "vendor/three.module.js",
        "vendor/three.core.js",
        "vendor/LICENSE",
    ):
        assert (SCENE / name).is_file(), name
    for name in ("main", "net", "room", "fly", "tv", "monitor", "theme", "orbit", "overlay"):
        assert (SCENE / "js" / f"{name}.js").is_file(), name


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_every_scene_script_parses():
    scripts = sorted(SCENE.rglob("*.js"))
    assert scripts
    for path in scripts:
        done = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
        assert done.returncode == 0, f"{path.name}:\n{done.stderr}"


# ------------------------------------------------------- a small client ----


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class WsClient:
    """Enough of a websocket client to test one: the handshake and reading
    unmasked server frames. No dependency, by design."""

    def __init__(self, host, port, path="/ws"):
        self.key = base64.b64encode(b"0123456789abcdef").decode("ascii")
        self.sock = socket.create_connection((host, port), timeout=8.0)
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {self.key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
        )
        self.reader = self.sock.makefile("rb")
        head = b""
        while not head.endswith(b"\r\n\r\n"):
            byte = self.reader.read(1)
            if not byte:
                raise AssertionError("the server closed during the handshake")
            head += byte
        self.head = head.decode("latin-1")

    def recv(self):
        return read_client_frame(self.reader)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# ------------------------------------------------- commands from the page ---


def masked_frame(payload: bytes, opcode: int = OP_TEXT) -> bytes:
    """A client-to-server frame, masked as a browser must send it."""
    mask = b"\x11\x22\x33\x44"
    size = len(payload)
    head = bytearray((0x80 | opcode,))
    if size < 126:
        head.append(0x80 | size)
    elif size <= 0xFFFF:
        head.append(0x80 | 126)
        head += size.to_bytes(2, "big")
    else:
        head.append(0x80 | 127)
        head += size.to_bytes(8, "big")
    return bytes(head) + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))


def test_the_server_takes_save_and_pause_from_the_page_and_ignores_the_rest(server):
    from flybrain.couch import parse_command

    client = WsClient(server.host, server.port)
    assert wait_for(lambda: server.hub.clients == 1)
    for frame in (
        masked_frame(b'{"cmd": "save"}'),
        masked_frame(b"not json at all"),
        masked_frame(b'{"cmd": "format c:"}'),
        masked_frame(b'["save"]'),
        masked_frame(b'{"cmd": ["save"]}'),
        masked_frame(bytes([0xFF, 0xFE, 0x00])),
        masked_frame(b'{"cmd": "save"}', OP_BINARY),
        masked_frame(b'{"cmd": "pause", "extra": 1}'),
        masked_frame(b"[" * 200 + b"]" * 200),
    ):
        client.sock.sendall(frame)
    assert wait_for(lambda: server.hub.commands_received == 2 and server.hub.frames_ignored == 6)
    assert server.hub.take_commands() == ["save", "pause"]
    assert server.hub.take_commands() == [], "each command is handed over once"
    client.close()

    assert parse_command(b'{"cmd": "save"}') == "save"
    assert parse_command(b'{"cmd": "' + b"x" * 400 + b'"}') is None


def test_a_flood_of_commands_cannot_grow_the_queue_or_reach_the_loop_late(server):
    from flybrain.couch import COMMAND_QUEUE

    client = WsClient(server.host, server.port)
    assert wait_for(lambda: server.hub.clients == 1)
    client.sock.sendall(masked_frame(b'{"cmd": "save"}') * 200)
    assert wait_for(lambda: server.hub.commands_received == 200)
    assert len(server.hub.take_commands()) == COMMAND_QUEUE
    client.close()


def test_an_oversized_client_frame_drops_that_client_and_the_feed_goes_on(server):
    watcher = CouchObserver(server.cfg, server.hub)
    bad = WsClient(server.host, server.port)
    assert wait_for(lambda: server.hub.clients == 1)
    bad.sock.sendall(masked_frame(b"x" * 70_000))
    assert wait_for(lambda: server.hub.clients == 0), "the reader gave up on it and the writer followed"
    bad.close()

    good = WsClient(server.host, server.port)
    watcher(a_tick(step=3))
    kinds = set()
    for _ in range(3):
        opcode, body = good.recv()
        kinds.add("video" if opcode == OP_BINARY else json.loads(body)["type"])
    good.close()
    assert kinds == {"hello", "state", "video"}


# ---------------------------------------------------- the journey fields ---


def test_a_milestone_is_latched_until_the_next_state_message():
    cfg = replace(Config(), couch_state_hz=0.5, couch_video_fps=0.5)
    hub = Hub()
    watcher = CouchObserver(cfg, hub)
    watcher(a_tick(step=1))
    landed = replace(a_tick(step=2), game_tick=15_120, milestone="left_house", milestones=("left_house",),
                     since_milestone=0, last_milestone="left_house", brain="latest.npz", brain_episodes=100)
    watcher(landed)  # not sent: the gate is closed
    watcher.state_ticker.reset()
    watcher(replace(landed, step=3, game_tick=15_121, milestone=None, milestones=(), since_milestone=1))
    state = state_in(hub)
    assert [m["name"] for m in state["milestones"]] == ["left_house"]
    assert state["milestones"][0]["game_time"] == "4:12" and state["milestones"][0]["label"] == "left the house"
    assert state["last_milestone"]["name"] == "left_house"
    assert state["game_time"] == "4:12" and state["generation"] == 100 and state["brain_file"] == "latest.npz"
    watcher.state_ticker.reset()
    watcher(replace(landed, step=4, game_tick=15_122, milestone=None, milestones=(), since_milestone=2))
    again = state_in(hub)
    assert again["milestones"] == [], "sent exactly once"
    assert again["last_milestone"]["name"] == "left_house" and again["since_milestone"] == 2


def test_the_replay_countdown_and_the_journey_status_ride_on_the_state():
    hub = Hub()
    watcher = CouchObserver(fast_config(), hub)
    watcher.replay_target = ("left_house", 15_120)
    watcher.extras = lambda: {"journey": True, "saved_ago": 12.0}
    watcher(replace(a_tick(step=1), game_tick=15_120 - 7 * 60))
    state = state_in(hub)
    assert state["countdown"]["text"] == "left the house in 0:07" and state["countdown"]["ticks"] == 420
    assert state["saved_ago"] == 12.0 and state["journey"] is True and state["paused"] is False
    watcher.state_ticker.reset()
    watcher(replace(a_tick(step=2), game_tick=15_121))
    assert state_in(hub)["countdown"] is None, "no countdown once it has landed"


def test_pausing_publishes_a_status_message():
    hub = Hub()
    watcher = CouchObserver(fast_config(), hub)
    watcher.extras = lambda: {"saved_ago": 3.0}
    watcher.on_pause(True)
    status = json.loads(payload_of(hub.latest("status")))
    assert status == {"type": "status", "paused": True, "saved_ago": 3.0}


def test_the_protocol_document_matches_the_version_and_the_new_messages():
    from flybrain.couch import PROTOCOL_VERSION

    text = (SCENE / "PROTOCOL.md").read_text(encoding="utf-8")
    assert f"`PROTOCOL_VERSION` is `{PROTOCOL_VERSION}`" in text
    for word in ('"cmd": "save"', '"cmd": "pause"', "### `status`", "countdown", "last_milestone", "saved_ago"):
        assert word in text, word
    net = (SCENE / "js" / "net.js").read_text(encoding="utf-8")
    assert f"export const PROTOCOL_VERSION = {PROTOCOL_VERSION};" in net


def test_a_second_scene_on_the_same_port_is_refused():
    """Two copies must never share a port: the browser would land on either."""
    from flybrain.couch import CouchServer

    first = CouchServer(port=0).start()
    port = first.port
    try:
        with pytest.raises(OSError, match="couch-port"):
            CouchServer(port=port)
    finally:
        first.stop()
