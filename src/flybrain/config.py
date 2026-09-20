"""Every tunable number in the project lives here.

One frozen dataclass. Nothing else in the package hard-codes a magic number:
if a value can be tuned, it is a field below with a comment saying what it does
and which way to move it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# The seven buttons the fly can press, in the order the motor pools are laid
# out at the end of the connectome index range.
POOL_NAMES: tuple[str, ...] = ("UP", "DOWN", "LEFT", "RIGHT", "A", "B", "START")

# Buttons that move the player. At most one of these is held at a time.
DIRECTIONS: frozenset[str] = frozenset({"UP", "DOWN", "LEFT", "RIGHT"})

# Buttons that are not directions. At most one of these is held at a time, but
# one of them may overlap with a direction.
ACTIONS: frozenset[str] = frozenset({"A", "B", "START"})

# Pokemon Red map ids, for the HUD and the run log. Only ids worth being sure
# about are listed; anything else is shown as its raw number rather than
# guessed at. 0x00, 0x25 and 0x26 are confirmed against this cartridge; the
# rest are the standard Gen 1 map constants and have not been seen in a run
# here yet. Note that this address reads 0 before the game has written to it,
# so a "Pallet Town" at the very start of a run from a cold boot is
# uninitialised RAM, not a place the fly has been.
MAP_NAMES: dict[int, str] = {
    0x00: "Pallet Town",
    0x01: "Viridian City",
    0x02: "Pewter City",
    0x03: "Cerulean City",
    0x04: "Lavender Town",
    0x05: "Vermilion City",
    0x06: "Celadon City",
    0x07: "Fuchsia City",
    0x08: "Cinnabar Island",
    0x09: "Indigo Plateau",
    0x0A: "Saffron City",
    0x0C: "Route 1",
    0x0D: "Route 2",
    0x25: "Red's house 1F",
    0x26: "Red's house 2F",
    0x27: "Blue's house",
    0x28: "Oak's Lab",
}


def map_name(map_id: int) -> str:
    """The map's name if it is one of the ids above, else the raw number."""
    return MAP_NAMES.get(map_id, f"map {map_id}")


# PyBoy's own button names, keyed by pool name.
BUTTON_FOR_POOL: dict[str, str] = {
    "UP": "up",
    "DOWN": "down",
    "LEFT": "left",
    "RIGHT": "right",
    "A": "a",
    "B": "b",
    "START": "start",
}


@dataclass(frozen=True)
class Config:
    """All tunables. Frozen: build a new one with `dataclasses.replace`."""

    # ---- run options ----------------------------------------------------
    rom_path: Path = Path("roms/pokemon_red.gb")
    headless: bool = False  # True -> PyBoy window="null", no SDL2 window
    uncapped: bool = False  # True -> emulation speed 0 (as fast as the CPU allows)
    hud: bool = True  # False -> one plain log line per second
    max_steps: int = 0  # 0 = run until the window closes or Ctrl+C
    seed: int = 0  # every RNG in the project derives from this
    connectome_csv: Path | None = None  # edge-list CSV instead of the synthetic net
    load_state: Path | None = None  # PyBoy savestate to start from
    save_state: Path | None = None  # PyBoy savestate to write on exit

    # ---- optic lobe -----------------------------------------------------
    retina_size: int = 16  # the 160x144 frame is area-averaged down to 16x16
    motion_gain: float = 0.45  # current per unit of rectified luminance delta
    tonic_gain: float = 0.20  # current per unit of absolute luminance; keeps a
    # static dialogue box producing drive. Raise if the
    # network goes quiet on still screens.
    dark_current: float = 0.075  # baseline current with no light at all, after the
    # photoreceptor dark current. Without it the fly is
    # blind and silent on the game's black screens.
    noise_sigma: float = 0.050  # per-step Gaussian current noise on every channel.
    # This is what keeps the net from ever going fully
    # silent, so do not drop it to zero outside tests.
    max_current: float = 0.25  # synaptic saturation: sensory current is clipped
    # here so a whole-screen flash cannot saturate the net

    # ---- connectome -----------------------------------------------------
    n_neurons: int = 2000  # total neurons, accepted in [1000, 5000]
    lattice_k: int = 20  # outgoing ring-lattice edges per neuron (even)
    rewire_p: float = 0.10  # Watts-Strogatz rewiring probability
    inhibitory_fraction: float = 0.20  # share of neurons that are inhibitory (Dale)
    pool_size: int = 24  # neurons per motor pool, 7 pools at the end
    w_exc: float = 0.170  # magnitude of every excitatory synapse
    inhibitory_balance: float = 1.0  # inhibitory synaptic scaling: how far each neuron's
    # incoming inhibition is rescaled to give every
    # neuron the same net lattice drive. 0.0 leaves the
    # raw random draw, which makes a pool's excitability
    # a lottery that swamps the retinotopic signal.
    w_inh: float = 0.595  # magnitude of every inhibitory synapse before balancing
    # Ratio to w_exc sets the excitation/inhibition balance:
    # raise to kill runaway activity, lower if the net dies.

    # retinotopic bias pathways: sensory -> interneuron -> motor pool
    bias_interneurons: int = 24  # interneurons per pathway
    bias_fan_in: int = 128  # sensory channels each of them pools from its region
    bias_lattice_scale: float = 0.15  # how much of the ordinary lattice input a bias
    # interneuron keeps. These are wide-field visual
    # cells; at 1.0 their 20 lattice synapses fluctuate
    # several times harder than the whole regional
    # signal and the retinotopy does nothing at all.
    w_bias_in: float = 0.015  # sensory -> bias interneuron, per pooled channel
    w_bias_out: float = 0.055  # bias interneuron -> motor pool. Much above this the
    # pools saturate and selectivity inverts.
    center_bias_scale: float = 0.45  # the centre -> A pathway is deliberately weaker

    # crossed inhibition between opposing pools, via inhibitory interneurons
    cross_inh_neurons: int = 10  # interneurons per opposing pair direction
    w_cross_in: float = 0.055  # pool -> crossed inhibitory interneuron
    w_cross_out: float = 0.120  # that interneuron -> the opposing pool (negative).
    # This is the amplifier that turns a 1.2x difference
    # in regional drive into a clear turning preference.
    # Ten interneurons land on each pool, so at 0.35 and
    # above the pair latches and whichever side wins
    # first stays won whatever the screen does.

    # ---- brain ----------------------------------------------------------
    leak: float = 0.10  # dt/tau in the LIF update; 0.10 = membrane tau of 10 steps
    v_rest: float = 0.0
    v_thresh: float = 1.0
    v_reset: float = 0.0
    refractory: int = 2  # steps a neuron is held at reset after spiking
    rate_smoothing: float = 0.05  # EMA factor for the firing rate the HUD shows

    # ---- motor ----------------------------------------------------------
    accum_decay: float = 0.85  # leak of each pool's fast spike accumulator per tick
    baseline_rate: float = 0.0033  # EMA rate of each pool's slow running baseline, so
    # tau is about 300 ticks. The baseline is the level
    # the pool's recent average drive would hold the
    # accumulator at, and it is computed from the spike
    # counts rather than from the accumulator, so a pool
    # firing cannot drag its own baseline around.
    adaptation: float = 1.0  # how much of the baseline is subtracted before the
    # threshold test. 1.0 = a pool fires only when it is
    # more active than it usually is; 0.0 = the absolute
    # level test, which saturates against the cooldown.
    fire_threshold: float = 6.4  # excursion above baseline that triggers a press.
    # Raise for a calmer fly, lower for a twitchier one.
    threshold_scale: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0, 1.0, 1.25, 2.2)
    # Per-pool multiplier on fire_threshold, in POOL_NAMES
    # order. START is a grooming bout and should be rare,
    # and B (withdraw) sits above A (interact).
    hold_frames: int = 4  # a press is held for exactly this many ticks
    cooldown_ticks: int = 8  # per-button silence after a release, so the game
    # registers distinct presses
    panic_after: int = 200  # ticks with the position unchanged, or with no button
    # pressed at all, before the anti-stuck reflex fires
    panic_min_buttons: int = 6  # shortest panic burst
    panic_max_buttons: int = 10  # longest panic burst
    panic_direction_weight: float = 3.0  # relative draw weight of UP/DOWN/LEFT/RIGHT
    panic_a_weight: float = 2.0  # relative draw weight of A
    panic_other_weight: float = 1.0  # relative draw weight of B and START
    panic_pulse: float = 0.22  # transient current added to every sensory channel
    # on the panic tick, so the startle shows on the HUD

    # ---- hud ------------------------------------------------------------
    hud_every: int = 6  # ticks between HUD redraws
    hud_history: int = 8  # actions kept in the "last actions" strip
    hud_bar_width: int = 20  # characters in an activation bar

    # ---- emulator -------------------------------------------------------
    map_id_addr: int = 0xD35E  # Pokemon Red: current map id
    player_y_addr: int = 0xD361  # Pokemon Red: player Y tile
    player_x_addr: int = 0xD362  # Pokemon Red: player X tile
    in_battle_addr: int = 0xD057  # Pokemon Red: nonzero while in a battle

    # ---- derived --------------------------------------------------------
    pool_names: tuple[str, ...] = field(default=POOL_NAMES)

    @property
    def n_sensory(self) -> int:
        """Two channels (ON and OFF) per downsampled pixel."""
        return 2 * self.retina_size * self.retina_size

    @property
    def n_motor(self) -> int:
        return self.pool_size * len(self.pool_names)
