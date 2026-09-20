import numpy as np

from flybrain.config import Config
from flybrain.optic_lobe import OpticLobe, region_masks


def frame(value: int) -> np.ndarray:
    return np.full((144, 160), value, dtype=np.uint8)


def test_shape_and_dtype():
    lobe = OpticLobe(Config())
    out = lobe.step(frame(120))
    assert out.shape == (512,)
    assert out.dtype == np.float32


def test_first_frame_has_zero_delta():
    """A quiet-noise, tonic-only config: the first frame must carry no motion."""
    cfg = Config(noise_sigma=0.0, tonic_gain=0.0, dark_current=0.0)
    lobe = OpticLobe(cfg)
    out = lobe.step(frame(200))
    assert np.allclose(out, 0.0)


def test_on_off_split_on_a_brightening_frame():
    cfg = Config(noise_sigma=0.0, tonic_gain=0.0, dark_current=0.0, motion_gain=1.0, max_current=10.0)
    lobe = OpticLobe(cfg)
    lobe.step(frame(0))
    out = lobe.step(frame(255))
    on, off = out[:256], out[256:]
    assert np.all(on > 0.9)
    assert np.all(off == 0.0)

    out = lobe.step(frame(0))  # darkening: the OFF channel takes it
    on, off = out[:256], out[256:]
    assert np.all(on == 0.0)
    assert np.all(off > 0.9)


def test_tonic_drive_on_a_static_screen():
    """A still bright screen must still produce drive, or the fly freezes on
    a dialogue box."""
    cfg = Config(noise_sigma=0.0)
    lobe = OpticLobe(cfg)
    lobe.step(frame(200))
    out = lobe.step(frame(200))
    assert np.all(out > 0.0)


def test_a_black_screen_still_produces_drive():
    """Pokemon Red shows a lot of black. Without the dark current the fly goes
    blind and the whole network falls silent."""
    cfg = Config(noise_sigma=0.0)
    lobe = OpticLobe(cfg)
    lobe.step(frame(0))
    out = lobe.step(frame(0))
    assert np.allclose(out, cfg.dark_current)


def test_current_is_clipped():
    cfg = Config(motion_gain=100.0)
    lobe = OpticLobe(cfg)
    lobe.step(frame(0))
    out = lobe.step(frame(255))
    assert out.max() <= cfg.max_current + 1e-6


def test_region_masks_partition_the_retina():
    masks = region_masks(16)
    assert set(masks) == {"left", "right", "top", "bottom", "centre"}
    for pair in (("left", "right"), ("top", "bottom")):
        a, b = masks[pair[0]], masks[pair[1]]
        assert a.size == b.size == 256  # half the pixels, ON and OFF
        assert np.intersect1d(a, b).size == 0
        assert np.union1d(a, b).size == 512
    assert masks["centre"].size == 128  # the middle 8x8, ON and OFF
