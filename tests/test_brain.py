import numpy as np

from flybrain.brain import Brain
from flybrain.config import POOL_NAMES, Config
from flybrain.connectome import synthetic
from flybrain.optic_lobe import OpticLobe

STEPS = 600


def random_frames(seed: int, steps: int = STEPS):
    rng = np.random.default_rng(seed)
    for _ in range(steps):
        yield rng.integers(0, 256, size=(144, 160), dtype=np.uint8)


def run(cfg: Config, seed: int = 0):
    conn = synthetic(n=cfg.n_neurons, k=cfg.lattice_k, rewire_p=cfg.rewire_p, seed=cfg.seed, cfg=cfg)
    lobe = OpticLobe(cfg)
    brain = Brain(conn, cfg)
    rates = []
    pool_totals = dict.fromkeys(POOL_NAMES, 0)
    for frame in random_frames(seed):
        spikes = brain.step(lobe.step(frame))
        rates.append(float(spikes.mean()))
        for name in POOL_NAMES:
            pool_totals[name] += int(spikes[conn.motor_pools[name]].sum())
    return np.array(rates), pool_totals


def test_network_neither_dies_nor_saturates():
    rates, pools = run(Config())
    mean = rates.mean()
    assert 0.005 <= mean <= 0.30, f"mean firing rate {mean:.4f} outside [0.5%, 30%]"
    for name, total in pools.items():
        assert total > 0, f"motor pool {name} never fired"


def test_it_is_still_alive_at_the_end_not_just_at_the_start():
    """A net that fires hard for 50 steps and then dies would still pass a mean
    check on its own, so look at the tail separately."""
    rates, _ = run(Config())
    assert 0.005 <= rates[-200:].mean() <= 0.30


def test_deterministic_under_a_seed():
    cfg = Config()
    a, _ = run(cfg)
    b, _ = run(cfg)
    assert np.array_equal(a, b)


def test_firing_rate_property_is_smoothed_and_in_range():
    cfg = Config()
    conn = synthetic(n=cfg.n_neurons, seed=cfg.seed, cfg=cfg)
    lobe = OpticLobe(cfg)
    brain = Brain(conn, cfg)
    for frame in random_frames(1, 200):
        brain.step(lobe.step(frame))
    assert 0.0 < brain.firing_rate < 0.30
    assert brain.steps == 200


def test_a_loaded_connectome_with_fewer_sensory_neurons_still_steps():
    """An edge list will not have exactly 512 sensory neurons; the optic lobe's
    channels are folded onto whatever it does have."""
    import tempfile
    from pathlib import Path

    from flybrain.connectome import from_edge_list

    cfg = Config()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "edges.csv"
        rows = ["pre,post,weight,sign"]
        for i in range(60):
            rows.append(f"{i},{(i + 1) % 60},0.2,1")
            rows.append(f"{i},{(i + 7) % 60},0.2,{1 if i % 5 else -1}")
        path.write_text("\n".join(rows), encoding="utf-8")
        conn = from_edge_list(path, cfg)
    brain = Brain(conn, cfg)
    lobe = OpticLobe(cfg)
    for frame in random_frames(0, 20):
        spikes = brain.step(lobe.step(frame))
    assert spikes.shape == (conn.n,)


def test_refractory_period_is_respected():
    cfg = Config(refractory=2)
    conn = synthetic(n=1100, seed=2, cfg=cfg)
    brain = Brain(conn, cfg)
    drive = np.full(cfg.n_sensory, 5.0, dtype=np.float32)  # far above threshold
    fired = [brain.step(drive)[conn.sensory_idx].mean() for _ in range(6)]
    # With refractory=2 a saturated sensory neuron cannot fire on consecutive steps.
    assert fired[0] == 1.0
    assert fired[1] == 0.0
    assert fired[2] == 0.0
