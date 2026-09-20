import numpy as np

from flybrain.config import ACTIONS, DIRECTIONS, POOL_NAMES, Config
from flybrain.connectome import synthetic
from flybrain.motor import MotorBridge


class FakeEmulator:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def press(self, button):
        self.calls.append(("press", button))

    def release(self, button):
        self.calls.append(("release", button))


def bridge(cfg=None):
    cfg = cfg or Config()
    conn = synthetic(n=1200, seed=0, cfg=cfg)
    sink = FakeEmulator()
    return MotorBridge(conn, cfg, sink), conn, sink, cfg


def spikes_for(conn, cfg, pools):
    vector = np.zeros(conn.n, dtype=bool)
    for name in pools:
        vector[conn.motor_pools[name]] = True
    return vector


def silence(conn):
    return np.zeros(conn.n, dtype=bool)


def test_press_is_held_for_exactly_four_frames_then_released():
    motor, conn, sink, cfg = bridge()
    driving = spikes_for(conn, cfg, ["UP"])
    motor.update(driving, (1, 1, 1))  # accumulator crosses on the first tick
    assert sink.calls == [("press", "up")]
    for _ in range(cfg.hold_frames - 1):
        motor.update(silence(conn), (1, 1, 1))
        assert sink.calls == [("press", "up")]
    motor.update(silence(conn), (1, 1, 1))
    assert sink.calls == [("press", "up"), ("release", "up")]


def test_cooldown_blocks_an_immediate_repress():
    motor, conn, sink, cfg = bridge()
    driving = spikes_for(conn, cfg, ["UP"])
    for _ in range(cfg.hold_frames + 1):
        motor.update(driving, (1, 1, 1))
    assert ("release", "up") in sink.calls
    presses = sum(1 for kind, button in sink.calls if kind == "press" and button == "up")
    for _ in range(cfg.cooldown_ticks - 1):
        motor.update(driving, (1, 1, 1))
    assert sum(1 for k, b in sink.calls if k == "press" and b == "up") == presses
    motor.update(driving, (1, 1, 1))
    assert sum(1 for k, b in sink.calls if k == "press" and b == "up") == presses + 1


def test_only_one_direction_is_held_at_a_time():
    motor, conn, sink, cfg = bridge()
    driving = spikes_for(conn, cfg, ["UP", "DOWN", "LEFT", "RIGHT"])
    for _ in range(60):
        motor.update(driving, (1, 1, 1))
        held_directions = [name for name in motor.held if name in DIRECTIONS]
        assert len(held_directions) <= 1
        held_actions = [name for name in motor.held if name in ACTIONS]
        assert len(held_actions) <= 1


def test_an_action_may_overlap_a_direction():
    motor, conn, sink, cfg = bridge()
    driving = spikes_for(conn, cfg, ["UP", "A"])
    overlapped = False
    for _ in range(40):
        motor.update(driving, (1, 1, 1))
        if any(n in DIRECTIONS for n in motor.held) and any(n in ACTIONS for n in motor.held):
            overlapped = True
    assert overlapped


def test_accumulator_resets_on_fire():
    motor, conn, sink, cfg = bridge()
    motor.update(spikes_for(conn, cfg, ["UP"]), (1, 1, 1))
    assert motor.accum[POOL_NAMES.index("UP")] == 0.0


def test_panic_fires_at_200_stuck_ticks_and_not_at_199():
    motor, conn, sink, cfg = bridge()
    quiet = silence(conn)
    for tick in range(cfg.panic_after - 1):
        assert motor.update(quiet, (1, 5, 5)) != "PANIC", f"panicked early at tick {tick + 1}"
    assert motor.panic_count == 0
    assert motor.stuck_ticks == cfg.panic_after - 1
    assert motor.update(quiet, (1, 5, 5)) == "PANIC"
    assert motor.panic_count == 1


def test_panic_resets_the_counter_and_queues_a_burst():
    motor, conn, sink, cfg = bridge()
    quiet = silence(conn)
    for _ in range(cfg.panic_after):
        motor.update(quiet, (1, 5, 5))
    assert motor.stuck_ticks == 0
    assert cfg.panic_min_buttons - 1 <= len(motor.queue) + 1 <= cfg.panic_max_buttons
    assert motor.take_pulse() == cfg.panic_pulse
    assert motor.take_pulse() == 0.0  # reading it clears it

    burst = len(motor.queue) + 1
    for _ in range(burst * (cfg.hold_frames + cfg.cooldown_ticks) + 10):
        motor.update(quiet, (1, 5, 5))
    assert not motor.queue
    presses = sum(1 for kind, _ in sink.calls if kind == "press")
    assert presses == burst
    assert motor.panic_count == 1


def test_movement_resets_the_stuck_counter():
    motor, conn, sink, cfg = bridge()
    quiet = silence(conn)
    for _ in range(150):
        motor.update(quiet, (1, 5, 5))
    assert motor.stuck_ticks == 150
    motor.update(quiet, (1, 6, 5))
    assert motor.stuck_ticks == 0
    for _ in range(cfg.panic_after - 1):
        motor.update(quiet, (1, 6, 5))
    assert motor.panic_count == 0


def test_a_new_action_resets_the_stuck_counter():
    motor, conn, sink, cfg = bridge()
    quiet = silence(conn)
    for _ in range(100):
        motor.update(quiet, (1, 5, 5))
    assert motor.stuck_ticks == 100
    motor.update(spikes_for(conn, cfg, ["A"]), (1, 5, 5))
    assert motor.stuck_ticks == 0


def test_release_all_is_safe_to_call_twice():
    motor, conn, sink, cfg = bridge()
    motor.update(spikes_for(conn, cfg, ["UP"]), (1, 1, 1))
    motor.release_all()
    motor.release_all()
    assert sink.calls == [("press", "up"), ("release", "up")]


def test_panic_burst_is_deterministic_under_a_seed():
    first, conn, _, cfg = bridge()
    second, _, _, _ = bridge()
    quiet = silence(conn)
    for _ in range(cfg.panic_after):
        first.update(quiet, (1, 5, 5))
        second.update(quiet, (1, 5, 5))
    assert first.queue == second.queue
