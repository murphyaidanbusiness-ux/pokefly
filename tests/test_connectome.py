import time

import numpy as np
import pytest

from flybrain.config import POOL_NAMES, Config
from flybrain.connectome import from_edge_list, synthetic


def test_size_and_layout():
    conn = synthetic(n=1500, seed=1)
    assert conn.n == 1500
    assert conn.weights.shape == (1500, 1500)
    assert conn.weights.dtype == np.float32
    assert np.array_equal(conn.sensory_idx, np.arange(512))
    assert set(conn.motor_pools) == set(POOL_NAMES)


def test_no_self_loops():
    conn = synthetic(n=1200, seed=2)
    assert np.all(np.diag(conn.weights) == 0.0)


def test_dale_law_holds():
    """Every outgoing synapse of a neuron has one sign."""
    conn = synthetic(n=2000, seed=3)
    column_positive = (conn.weights > 0).any(axis=0)
    column_negative = (conn.weights < 0).any(axis=0)
    assert not np.any(column_positive & column_negative)


def test_pools_are_disjoint_and_the_right_size():
    cfg = Config()
    conn = synthetic(n=2000, seed=4, cfg=cfg)
    seen: set[int] = set()
    for name in POOL_NAMES:
        pool = conn.motor_pools[name]
        assert pool.size == cfg.pool_size
        assert not seen & set(pool.tolist())
        seen |= set(pool.tolist())
    assert max(seen) == 1999  # the pools sit at the end of the index range
    assert min(seen) == 2000 - cfg.n_motor


def test_inhibitory_fraction_and_protected_neurons():
    cfg = Config()
    conn = synthetic(n=2000, seed=5, cfg=cfg)
    inhibitory = (conn.weights < 0).any(axis=0)
    assert not inhibitory[conn.sensory_idx].any()  # sensory neurons are excitatory
    assert not inhibitory[conn.motor_idx].any()  # so are the motor pools
    assert 0.15 < inhibitory.mean() < 0.25


def test_crossed_inhibition_reaches_the_opposing_pool():
    conn = synthetic(n=2000, seed=6)
    for source, target in (("UP", "DOWN"), ("LEFT", "RIGHT")):
        block = conn.weights[np.ix_(conn.motor_pools[target], np.arange(conn.n))]
        assert (block < 0).any(), f"{source} has no inhibitory route into {target}"


def test_deterministic_under_a_seed():
    a = synthetic(n=1300, seed=7)
    b = synthetic(n=1300, seed=7)
    c = synthetic(n=1300, seed=8)
    assert np.array_equal(a.weights, b.weights)
    assert not np.array_equal(a.weights, c.weights)


def test_builds_fast_at_5000():
    started = time.perf_counter()
    conn = synthetic(n=5000, seed=9)
    elapsed = time.perf_counter() - started
    assert conn.n == 5000
    assert elapsed < 2.0, f"took {elapsed:.2f}s"


def test_rejects_out_of_range_n():
    with pytest.raises(ValueError):
        synthetic(n=500)
    with pytest.raises(ValueError):
        synthetic(n=6000)


def test_edge_list_loader(tmp_path):
    csv_path = tmp_path / "tiny.csv"
    csv_path.write_text(
        "pre,post,weight,sign\n"
        "a,b,1.0,1\n"
        "a,c,2.0,1\n"
        "b,c,0.5,-1\n"
        "b,d,0.5,-1\n"
        "c,d,3.0,1\n"
        "d,a,1.5,1\n",
        encoding="utf-8",
    )
    conn = from_edge_list(csv_path)
    assert conn.n == 4
    assert conn.weights.shape == (4, 4)
    column_positive = (conn.weights > 0).any(axis=0)
    column_negative = (conn.weights < 0).any(axis=0)
    assert not np.any(column_positive & column_negative)  # Dale again
    assert np.all(np.diag(conn.weights) == 0.0)
    assert set(conn.motor_pools) == set(POOL_NAMES)
    assert conn.sensory_idx.size >= 1


def test_edge_list_without_a_sign_column(tmp_path):
    csv_path = tmp_path / "unsigned.csv"
    csv_path.write_text("pre,post,weight\n1,2,1.0\n2,3,-2.0\n3,1,1.0\n", encoding="utf-8")
    conn = from_edge_list(csv_path)
    assert conn.n == 3
    assert (conn.weights < 0).any()  # neuron 2's negative outgoing weight survived
