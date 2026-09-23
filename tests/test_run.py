"""`run.py` on a fresh clone: `roms/`, `states/` and `brains/` are all
gitignored, so the first run may be missing any of them, and each case has to
end in one line and exit code 2 rather than a traceback under a half-drawn
HUD. None of this needs Pokemon Red: the ROM checks use a path that does not
exist, and the state check uses PyBoy's bundled demo ROM."""

from pathlib import Path

import pyboy
import pytest

import run

BUNDLED_ROM = Path(pyboy.__file__).resolve().parent / "default_rom.gb"


def main_with(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", ["run.py", *argv])
    with pytest.raises(SystemExit) as excinfo:
        run.main()
    return excinfo.value.code


def test_a_missing_rom_exits_2_before_the_journey_folder_is_made(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "JOURNEY_DIR", tmp_path / "journey")
    code = main_with(monkeypatch, ["--rom", str(tmp_path / "nope.gb")])
    assert code == 2
    err = capsys.readouterr().err
    assert "ROM not found" in err
    assert not (tmp_path / "journey").exists(), "nothing was made for a run that could not start"


def test_a_missing_start_state_exits_2_and_says_how_to_make_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "JOURNEY_DIR", tmp_path / "journey")
    monkeypatch.setattr(run, "BEDROOM", tmp_path / "bedroom.state")
    code = main_with(monkeypatch, ["--rom", str(BUNDLED_ROM), "--headless", "--no-hud", "--max-steps", "1"])
    assert code == 2
    err = capsys.readouterr().err
    assert "savestate not found" in err and "--make-start-state" in err
    assert not (tmp_path / "journey").exists()


def test_a_missing_load_state_exits_2(tmp_path, monkeypatch, capsys):
    code = main_with(
        monkeypatch,
        ["--rom", str(BUNDLED_ROM), "--headless", "--no-hud", "--max-steps", "1", "--load-state", str(tmp_path / "x.state")],
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "savestate not found" in err and "--make-start-state" not in err


def test_the_hud_gives_the_cursor_back_when_the_run_never_starts(tmp_path, monkeypatch, capsys):
    """With the HUD on, a run that dies before the loop must still print the
    show-cursor escape, or the terminal is left without a cursor."""
    from flybrain.hud import Hud

    closed = []
    real_close = Hud.close

    def close(self):
        closed.append(1)
        real_close(self)

    monkeypatch.setattr(Hud, "close", close)
    monkeypatch.setattr(run, "JOURNEY_DIR", tmp_path / "journey")
    # The state exists but is not a PyBoy savestate, so run_loop fails inside
    # _set_up, after the HUD was built and before the loop closes anything.
    state = tmp_path / "bad.state"
    state.write_bytes(b"\x00" * 16)
    monkeypatch.setattr("sys.argv", ["run.py", "--rom", str(BUNDLED_ROM), "--headless", "--max-steps", "1", "--load-state", str(state)])
    with pytest.raises(BaseException):
        run.main()
    assert closed, "the display was closed on the way out"
    assert "\x1b[?25h" in capsys.readouterr().out
