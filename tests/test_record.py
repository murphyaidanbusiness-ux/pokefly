"""`run.py --record`: the CDP client, the pacer, the take's plumbing, and one
real take in headless Edge or Chrome when there is one (skipped cleanly when
there is not). The real take uses the ROM PyBoy ships for its own demo, so it
needs no Pokemon ROM, and it writes nothing outside pytest's tmp_path."""

import io
import json
import queue
import socket
import threading
import time
from pathlib import Path

import pyboy
import pytest

import run
from flybrain.config import Config, dynamics_fingerprint
from flybrain.couch import OP_BINARY, OP_PING, OP_PONG, OP_TEXT, CouchServer, accept_key, encode_frame, read_frame
from flybrain.record import (
    LANDSCAPE_SIZE,
    PORTRAIT_SIZE,
    Cdp,
    CdpError,
    HandshakeError,
    Pacer,
    Recorder,
    RecordResult,
    WebSocketClient,
    check_handshake,
    client_key,
    connect,
    encode_client_frame,
    ffmpeg_command,
    ffmpeg_exe,
    find_browser,
    frame_indices,
    frame_size,
    handshake_request,
    open_writer,
)

BUNDLED_ROM = Path(pyboy.__file__).resolve().parent / "default_rom.gb"

# ------------------------------------------------------------- websocket ---

# RFC 6455 section 1.3 and 5.7: the sample nonce, its accept value, and the
# masked single-frame "Hello" with its masking key.
RFC_KEY = "dGhlIHNhbXBsZSBub25jZQ=="
RFC_ACCEPT = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
RFC_MASK = bytes([0x37, 0xFA, 0x21, 0x3D])
RFC_MASKED_HELLO = bytes([0x81, 0x85, 0x37, 0xFA, 0x21, 0x3D, 0x7F, 0x9F, 0x4D, 0x51, 0x58])
RFC_UNMASKED_HELLO = bytes([0x81, 0x05, 0x48, 0x65, 0x6C, 0x6C, 0x6F])


def test_a_masked_client_frame_matches_the_rfc_example():
    assert encode_client_frame(b"Hello", OP_TEXT, RFC_MASK) == RFC_MASKED_HELLO


def test_the_rfc_example_reads_back_unmasked_either_way():
    assert read_frame(io.BytesIO(RFC_MASKED_HELLO)) == (True, OP_TEXT, b"Hello")
    assert read_frame(io.BytesIO(RFC_UNMASKED_HELLO)) == (True, OP_TEXT, b"Hello")


@pytest.mark.parametrize("size", [0, 125, 126, 65535, 65536, 300_000])
def test_a_masked_frame_of_any_length_reads_back(size):
    body = bytes(range(256)) * (size // 256) + bytes(size % 256)
    framed = encode_client_frame(body, OP_BINARY)
    assert framed[1] & 0x80, "the mask bit is set"
    assert read_frame(io.BytesIO(framed), limit=1 << 20) == (True, OP_BINARY, body)


def test_every_frame_gets_a_fresh_masking_key():
    assert encode_client_frame(b"same") != encode_client_frame(b"same")


def test_the_handshake_key_and_request_are_what_the_rfc_asks_for():
    key = client_key()
    assert len(key) == 24 and len(__import__("base64").b64decode(key)) == 16
    request = handshake_request("127.0.0.1", 9222, "/devtools/browser/abc", RFC_KEY).decode("ascii")
    assert request.startswith("GET /devtools/browser/abc HTTP/1.1\r\n")
    for header in ("Host: 127.0.0.1:9222", "Upgrade: websocket", "Connection: Upgrade",
                   f"Sec-WebSocket-Key: {RFC_KEY}", "Sec-WebSocket-Version: 13"):
        assert header + "\r\n" in request
    assert request.endswith("\r\n\r\n")


def test_the_handshake_reply_is_checked_against_the_rfc_accept_value():
    good = (
        "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {RFC_ACCEPT}\r\n\r\n"
    ).encode("ascii")
    check_handshake(good, RFC_KEY)
    with pytest.raises(HandshakeError):
        check_handshake(good.replace(RFC_ACCEPT.encode(), accept_key("other").encode()), RFC_KEY)
    with pytest.raises(HandshakeError):
        check_handshake(b"HTTP/1.1 400 Bad Request\r\n\r\n", RFC_KEY)


class _Wire:
    """What a WebSocketClient writes, as bytes."""

    def __init__(self):
        self.sent = bytearray()

    def __call__(self, data):
        self.sent += data


def test_the_client_joins_fragments_and_answers_a_ping():
    stream = (
        encode_frame(b"ping!", OP_PING)
        + bytes([0x01, 0x03]) + b"abc"  # text, FIN clear
        + bytes([0x00, 0x03]) + b"def"  # continuation, FIN clear
        + bytes([0x80, 0x03]) + b"ghi"  # continuation, FIN set
    )
    wire = _Wire()
    client = WebSocketClient(io.BytesIO(stream), wire)
    assert client.receive() == (OP_TEXT, b"abcdefghi")
    fin, opcode, payload = read_frame(io.BytesIO(bytes(wire.sent)))
    assert (fin, opcode, payload) == (True, OP_PONG, b"ping!"), "a pong with the ping's payload, masked"
    assert client.receive() is None, "end of stream is a close"


def test_the_client_shakes_hands_with_the_couch_server_and_reads_its_feed():
    """Both halves in this repository, talking to each other over a socket:
    our client's handshake against our server's, and the hello the server
    publishes coming out of receive()."""
    server = CouchServer(Config(), port=0).start()
    try:
        server.hub.publish("hello", encode_frame(b'{"type": "hello"}', OP_TEXT))
        client = connect(f"ws://127.0.0.1:{server.port}/ws", timeout=5.0)
        try:
            assert client.receive() == (OP_TEXT, b'{"type": "hello"}')
            client.send_text('{"cmd": "save"}')
            deadline = time.monotonic() + 5.0
            while server.hub.commands_received == 0 and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.hub.take_commands() == ["save"], "the server unmasked what the client masked"
        finally:
            client.close()
    finally:
        server.stop()


def test_a_server_that_does_not_upgrade_is_refused():
    server = CouchServer(Config(), port=0).start()
    try:
        with pytest.raises(HandshakeError):
            connect(f"ws://127.0.0.1:{server.port}/index.html", timeout=5.0)
    finally:
        server.stop()


# -------------------------------------------------------------------- cdp ---


class FakeSocket:
    """A websocket the test plays the browser on: whatever the Cdp sends lands
    in `sent`, and whatever the test feeds comes out of receive()."""

    def __init__(self):
        self.sent: list[dict] = []
        self.inbox: queue.Queue = queue.Queue()
        self.arrived = threading.Condition()

    def send_text(self, text):
        with self.arrived:
            self.sent.append(json.loads(text))
            self.arrived.notify_all()

    def receive(self):
        item = self.inbox.get(timeout=10)
        return None if item is None else (OP_TEXT, json.dumps(item).encode("utf-8"))

    def feed(self, message):
        self.inbox.put(message)

    def close(self):
        self.inbox.put(None)

    def wait_for(self, count):
        with self.arrived:
            assert self.arrived.wait_for(lambda: len(self.sent) >= count, timeout=5)


def test_each_call_gets_the_reply_with_its_own_id_whatever_the_order():
    wire = FakeSocket()
    cdp = Cdp(wire)
    results = {}

    def ask(name):
        results[name] = cdp.call(name, {"n": name}, session="S1")

    threads = [threading.Thread(target=ask, args=(name,)) for name in ("First.one", "Second.one")]
    for thread in threads:
        thread.start()
    wire.wait_for(2)
    by_method = {message["method"]: message for message in wire.sent}
    assert {message["id"] for message in wire.sent} == {1, 2}
    assert all(message["sessionId"] == "S1" for message in wire.sent)
    # The browser answers the second question first, with an event between.
    wire.feed({"method": "Page.loadEventFired", "params": {}})
    wire.feed({"id": by_method["Second.one"]["id"], "result": {"answer": "second"}})
    wire.feed({"id": by_method["First.one"]["id"], "result": {"answer": "first"}})
    for thread in threads:
        thread.join(timeout=5)
    assert results == {"First.one": {"answer": "first"}, "Second.one": {"answer": "second"}}
    cdp.close()


def test_an_error_reply_raises_and_events_reach_their_handler():
    wire = FakeSocket()
    cdp = Cdp(wire)
    seen = []
    cdp.on("Page.screencastFrame", lambda params, session: seen.append((params, session)))
    wire.feed({"method": "Page.screencastFrame", "params": {"sessionId": 3}, "sessionId": "S1"})
    failure = []
    thread = threading.Thread(target=lambda: failure.append(pytest.raises(CdpError, cdp.call, "Bad.method")))
    thread.start()
    wire.wait_for(1)
    wire.feed({"id": wire.sent[0]["id"], "error": {"code": -32601, "message": "'Bad.method' wasn't found"}})
    thread.join(timeout=5)
    assert "wasn't found" in str(failure[0].value)
    assert seen == [({"sessionId": 3}, "S1")]
    cdp.close()


def test_a_call_waiting_when_the_browser_hangs_up_fails_instead_of_hanging():
    wire = FakeSocket()
    cdp = Cdp(wire)
    errors = []

    def ask():
        try:
            cdp.call("Page.navigate", {"url": "x"}, timeout=10)
        except CdpError as error:
            errors.append(str(error))

    thread = threading.Thread(target=ask)
    thread.start()
    wire.wait_for(1)
    wire.close()
    thread.join(timeout=5)
    assert errors and "closed" in errors[0]
    with pytest.raises(CdpError):
        cdp.call("Anything")


def test_every_screencast_frame_is_acked_at_once_and_only_frames_of_the_take_are_kept():
    wire = FakeSocket()
    recorder = Recorder(Config(), "http://x/", "unused.mp4", 1.0)
    recorder.cdp = Cdp(wire, start=False)
    frame = {"data": "AAAA", "metadata": {"timestamp": time.time() - 5}, "sessionId": 41}
    recorder.on_frame(frame, "S1")  # before begin(): acked, not kept
    recorder.begin()
    recorder.on_frame(frame, "S1")  # stamped before begin(): acked, not kept
    fresh = {"data": "BBBB", "metadata": {"timestamp": time.time() + 1}, "sessionId": 42}
    recorder.on_frame(fresh, "S1")
    acks = [message for message in wire.sent if message["method"] == "Page.screencastFrameAck"]
    assert [ack["params"] for ack in acks] == [{"sessionId": 41}, {"sessionId": 41}, {"sessionId": 42}]
    assert all(ack["sessionId"] == "S1" for ack in acks), "acked on the page's own session"
    assert recorder._frames.qsize() == 1 and recorder._frames.get()[1] == "BBBB"


def test_a_full_backlog_drops_and_counts_but_still_acks():
    wire = FakeSocket()
    cfg = Config()
    from dataclasses import replace

    recorder = Recorder(replace(cfg, couch_record_backlog=2), "http://x/", "unused.mp4", 1.0)
    recorder.cdp = Cdp(wire, start=False)
    recorder.begin()
    for index in range(5):
        recorder.on_frame({"data": "A", "metadata": {"timestamp": time.time() + 1}, "sessionId": index}, "S")
    assert recorder.result.dropped == 3
    assert len(wire.sent) == 5


# ------------------------------------------------------------------ pacing ---


def steady(fps, seconds, start=1000.0):
    return [start + i / fps for i in range(int(round(fps * seconds)))]


def test_captures_at_the_file_rate_map_one_to_one():
    assert frame_indices(steady(60, 2), 60, 2) == list(range(120))


def test_a_slow_capture_is_repeated_to_fill_the_gaps():
    indices = frame_indices(steady(30, 2), 60, 2)
    assert len(indices) == 120
    assert indices == [i // 2 for i in range(120)]


def test_a_fast_capture_drops_the_extras_and_never_runs_behind():
    stamps = steady(120, 2)
    indices = frame_indices(stamps, 60, 2)
    assert len(indices) == 120
    assert indices == sorted(indices), "time never runs backwards"
    assert len(set(indices)) == 120, "one capture per slot, the rest dropped"
    for slot, index in enumerate(indices):
        # the picture in slot k was captured within about a slot of k / 60
        assert abs((stamps[index] - stamps[0]) * 60 - slot) <= 1.5


def test_a_gap_in_the_captures_is_filled_with_the_last_frame():
    stamps = [1000 + i / 60 for i in range(30)] + [1000 + i / 60 for i in range(40, 120)]
    indices = frame_indices(stamps, 60, 2)
    assert len(indices) == 120
    assert indices[29:40] == [29] * 11, "the frame before the gap holds through it"
    assert indices[40] == 30


def test_jitter_of_half_a_frame_either_way_loses_nothing():
    """The screencast's stamps wobble like this under load (median 16.2 ms,
    10th and 90th percentiles 8 and 27): every capture still gets a slot."""
    import numpy as np

    rng = np.random.default_rng(0)
    stamps = sorted(1000 + i / 60 + rng.uniform(-0.0075, 0.0075) for i in range(600))
    indices = frame_indices(stamps, 60, 10)
    assert len(indices) == 600
    assert len(set(indices)) >= 590


@pytest.mark.parametrize("fps,seconds", [(60, 3), (30, 3), (60, 20), (60, 7.5)])
def test_the_file_is_exactly_fps_times_seconds_frames(fps, seconds):
    import numpy as np

    rng = np.random.default_rng(1)
    # 50 captures a second with jitter, running past the end
    stamps = np.cumsum(rng.uniform(0.008, 0.032, size=int(seconds * 80)))
    assert len(frame_indices(stamps, fps, seconds)) == round(fps * seconds)
    # and a capture that stops early still fills to the end
    assert len(frame_indices(stamps[:10], fps, seconds)) == round(fps * seconds)


def test_a_take_stopped_early_ends_on_its_last_capture():
    pacer = Pacer(60, 10)
    counts = [pacer.push(stamp) for stamp in steady(60, 1)]
    assert sum(counts) == 59
    assert pacer.finish(fill=False) == 1
    assert pacer.written == 60 and not pacer.done


# ------------------------------------------------------------------ run.py ---


def test_record_implies_a_headless_couch_with_no_tab_and_no_window():
    cfg, options, args = run.parse_args(["--record", "out.mp4", "--window", "--no-journey"])
    assert args.couch and args.no_browser and not args.window
    assert cfg.headless


def test_record_flags_need_record_and_record_refuses_fresh():
    with pytest.raises(SystemExit):
        run.parse_args(["--seconds", "5"])
    with pytest.raises(SystemExit):
        run.parse_args(["--record", "x.mp4", "--fresh"])
    with pytest.raises(SystemExit):
        run.parse_args(["--record", "x.mp4", "--seconds", "0"])


def test_the_file_is_portrait_or_landscape_at_exactly_1080_by_1920():
    assert frame_size(True) == PORTRAIT_SIZE == (1080, 1920)
    assert frame_size(False) == LANDSCAPE_SIZE == (1920, 1080)


def test_the_scene_url_carries_portrait_and_the_extra_parameters():
    assert run.scene_url("http://h:1/", False) == "http://h:1/"
    assert run.scene_url("http://h:1/", True) == "http://h:1/?portrait=1"
    assert run.scene_url("http://h:1/", True, "view=4&clean=1") == "http://h:1/?portrait=1&view=4&clean=1"
    assert run.scene_url("http://h:1/", False, "?orbit=1") == "http://h:1/?orbit=1"


def test_the_record_settings_are_not_part_of_the_fly():
    """A journey save and a replay carry a fingerprint of every number that
    decides a tick; the recorder's numbers must not be in it, or adding them
    would have made every save on disk unloadable."""
    from dataclasses import replace

    cfg = Config()
    changed = replace(cfg, couch_record_fps=30, couch_record_seconds=5.0, couch_record_quality=50)
    assert dynamics_fingerprint(cfg) == dynamics_fingerprint(changed)


def test_a_take_with_no_journey_save_writes_nothing(tmp_path, monkeypatch):
    bedroom = tmp_path / "bedroom.state"
    bedroom.write_bytes(b"x")
    monkeypatch.setattr(run, "BEDROOM", bedroom)
    monkeypatch.setattr(run, "ROOT", tmp_path)
    cfg, options, args = run.parse_args(["--record", "x.mp4", "--no-learn"])
    assert args.journey
    store = run.JourneySave(tmp_path / "journey")
    cfg = run.set_up_take(cfg, options, args, store)
    assert cfg.load_state == bedroom
    assert options.journey is None and options.recorder is None
    assert not (tmp_path / "journey").exists(), "no journey folder, no brain copy"


def test_the_take_starts_once_the_page_has_had_a_game_frame():
    class Stub:
        videos_sent = 0

    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

    began = []
    recorder = type("R", (), {"begin": lambda self: began.append(1)})()
    watcher, clock = Stub(), Clock()
    starter = run.TakeStarter(recorder, watcher, 0.15, clock=clock)
    starter(None)
    clock.now = 0.1
    watcher.videos_sent = 1
    starter(None)
    clock.now = 0.2
    starter(None)
    assert not began, "not until the frame has had its lead"
    clock.now = 0.26
    starter(None)
    starter(None)
    assert began == [1]


def test_a_take_whose_page_never_gets_a_frame_still_starts():
    watcher = type("W", (), {"videos_sent": 0})()
    began = []
    recorder = type("R", (), {"begin": lambda self: began.append(1)})()
    now = [0.0]
    starter = run.TakeStarter(recorder, watcher, 0.15, clock=lambda: now[0])
    starter(None)
    now[0] = 2.5
    starter(None)
    assert began == [1]


# ---------------------------------------------------------------- encoder ---


def test_the_ffmpeg_call_pipes_raw_bgr_into_libx264():
    command = ffmpeg_command("ffmpeg.exe", "out.mp4", (1080, 1920), 60, 23)
    assert command[0] == "ffmpeg.exe" and command[-1] == "out.mp4"

    def after(flag, start=0):
        return command[command.index(flag, start) + 1]

    # the input: raw BGR frames of exactly the file's size and rate, on stdin
    assert after("-f") == "rawvideo"
    assert after("-pix_fmt") == "bgr24"
    assert after("-s") == "1080x1920"
    assert after("-r") == "60"
    assert after("-i") == "-"
    # the output, after the input: H.264 in yuv420p, index at the front
    output = command.index("-i")
    assert after("-c:v", output) == "libx264"
    assert after("-preset", output) == "veryfast"
    assert after("-crf", output) == "23"
    assert after("-pix_fmt", output) == "yuv420p"
    assert after("-movflags", output) == "+faststart"
    assert after("-r", output) == "60"
    assert "-y" in command, "a re-render overwrites the old file instead of hanging on a prompt"
    assert ffmpeg_command("f", "o.mp4", (1920, 1080), 30, 18)[command.index("-s") + 1] == "1920x1080"


def test_the_encoder_falls_back_to_mp4v_without_imageio_ffmpeg(tmp_path):
    import numpy as np

    writer, name = open_writer(tmp_path / "fallback.mp4", (64, 48), 30, 23, exe="")
    assert name.startswith("mp4v") and "imageio-ffmpeg" in name
    writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
    writer.release()
    assert (tmp_path / "fallback.mp4").stat().st_size > 0


@pytest.mark.skipif(ffmpeg_exe() is None, reason="imageio-ffmpeg is not installed")
def test_the_ffmpeg_writer_makes_a_file_opencv_can_read(tmp_path):
    import cv2
    import numpy as np

    out = tmp_path / "x264.mp4"
    writer, name = open_writer(out, (128, 96), 30, 23)
    assert name.startswith("libx264 crf 23")
    for index in range(30):
        frame = np.zeros((96, 128, 3), dtype=np.uint8)
        frame[:, index * 4 : index * 4 + 8] = 255
        writer.write(frame)
    writer.release()
    capture = cv2.VideoCapture(str(out))
    assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 30
    ok, first = capture.read()
    capture.release()
    assert ok and first.shape == (96, 128, 3)


def test_record_crf_is_checked_and_needs_record():
    assert run.parse_args(["--record", "x.mp4", "--record-crf", "18"])[2].record_crf == 18
    with pytest.raises(SystemExit):
        run.parse_args(["--record", "x.mp4", "--record-crf", "60"])
    with pytest.raises(SystemExit):
        run.parse_args(["--record-crf", "18"])


def test_a_slow_capture_is_reported_loudly():
    slow = RecordResult(path="x.mp4", fps=60, frames=600, captured=200)
    assert slow.slow and "UNDER 50" in slow.warning()
    fine = RecordResult(path="x.mp4", fps=60, frames=600, captured=590)
    assert not fine.slow and fine.warning() is None


# ------------------------------------------------------------- a real take ---


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.skipif(find_browser() is None, reason="no Edge or Chrome on this machine")
def test_three_seconds_of_the_scene_headless(tmp_path, monkeypatch):
    import cv2
    import numpy as np

    # Nothing of the user's is touched: no journey, no milestones folder.
    monkeypatch.setattr(run, "MILESTONES", tmp_path / "milestones")
    monkeypatch.setattr(run, "JOURNEY_DIR", tmp_path / "journey")
    out = tmp_path / "take.mp4"
    result = run.main(
        [
            "--rom", str(BUNDLED_ROM), "--naive", "--no-journey", "--no-hud", "--portrait",
            "--record", str(out), "--seconds", "3", "--couch-port", str(_free_port()),
        ]
    )
    assert result is not None and result.error is None, result and result.line()
    assert out.is_file()
    capture = cv2.VideoCapture(str(out))
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    assert 170 <= len(frames) <= 190, len(frames)
    assert result.frames == 180
    assert frames[0].shape == (1920, 1080, 3)
    middle = frames[len(frames) // 2]
    assert middle.mean() > 10, "not black"
    assert np.abs(middle.astype(int) - frames[0].astype(int)).mean() > 0.5, "the picture moves"
    assert not (tmp_path / "milestones").exists() and not (tmp_path / "journey").exists()
    # Small enough to post: under 5 MB a second of video. OpenCV's mp4v writes
    # about 17 MB a second at this size and fails this.
    megabytes_per_second = out.stat().st_size / 1e6 / 3.0
    assert megabytes_per_second < 5.0, f"{megabytes_per_second:.1f} MB/s from {result.encoder}"
    assert result.encoder.startswith("libx264"), result.encoder
