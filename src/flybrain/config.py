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
    0x29: "Viridian Pokemon Center",
    0x2A: "Viridian Mart",
    0x2F: "Viridian Forest north gate",
    0x31: "Route 2 gate",
    0x32: "Viridian Forest south gate",
    0x33: "Viridian Forest",
    0x36: "Pewter Gym",
    0x3A: "Pewter Pokemon Center",
}

# Map ids the milestones test against. Every one is from pret/pokered
# `constants/map_constants.asm` (the `map_const` lines, whose trailing comment
# is the id), read 2026-09-22. The first four were also seen in runs here.
PALLET_TOWN = 0x00  # PALLET_TOWN
VIRIDIAN_CITY = 0x01  # VIRIDIAN_CITY
PEWTER_CITY = 0x02  # PEWTER_CITY
ROUTE_1 = 0x0C  # ROUTE_1
REDS_HOUSE_1F = 0x25  # REDS_HOUSE_1F
REDS_HOUSE_2F = 0x26  # REDS_HOUSE_2F
OAKS_LAB = 0x28  # OAKS_LAB
VIRIDIAN_FOREST = 0x33  # VIRIDIAN_FOREST
# Every `*_POKECENTER` constant in the same file. The Indigo Plateau lobby
# heals too but is not named a Pokemon Center there, so it is not in the set.
POKEMON_CENTERS: frozenset[int] = frozenset(
    {
        0x29,  # VIRIDIAN_POKECENTER
        0x3A,  # PEWTER_POKECENTER
        0x40,  # CERULEAN_POKECENTER
        0x44,  # MT_MOON_POKECENTER
        0x51,  # ROCK_TUNNEL_POKECENTER
        0x59,  # VERMILION_POKECENTER
        0x85,  # CELADON_POKECENTER
        0x8D,  # LAVENDER_POKECENTER
        0x9A,  # FUCHSIA_POKECENTER
        0xAB,  # CINNABAR_POKECENTER
        0xB6,  # SAFFRON_POKECENTER
    }
)
# wIsInBattle: "lost battle, this is -1; no battle, this is 0; wild battle,
# this is 1; trainer battle, this is 2" (ram/wram.asm).
BATTLE_LOST = 0xFF


def map_name(map_id: int) -> str:
    """The map's name if it is one of the ids above, else the raw number."""
    return MAP_NAMES.get(map_id, f"map {map_id}")


# A rough ordering of the early game, for the one word "furthest" in a training
# log row. It is a heuristic and it is only meant to cover the stretch this
# project can reach: bedroom, downstairs, outside, the two Pallet buildings,
# Route 1, Viridian. Ties are deliberate (the lab and the rival's house are
# both "in Pallet, indoors"). A map that is not listed ranks -1 and is reported
# by id rather than folded into this scale.
MAP_PROGRESS: dict[int, int] = {
    0x26: 0,  # Red's house 2F, where an episode starts
    0x25: 1,  # Red's house 1F
    0x00: 2,  # Pallet Town: out of the house, the primary acceptance
    0x27: 3,  # Blue's house
    0x28: 3,  # Oak's Lab
    0x0C: 4,  # Route 1
    0x01: 5,  # Viridian City
    0x0D: 6,  # Route 2
    0x02: 7,  # Pewter City
}


def map_progress(map_id: int) -> int:
    return MAP_PROGRESS.get(map_id, -1)


def furthest_map(map_ids) -> int | None:
    """The most advanced of the maps given, by `MAP_PROGRESS`, or None."""
    ranked = [m for m in map_ids if map_progress(m) >= 0]
    return max(ranked, key=map_progress) if ranked else None


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

    # ---- couch scene ----------------------------------------------------
    # `run.py --couch`: a stdlib HTTP + WebSocket server on loopback feeding a
    # three.js scene in the browser. Nothing here is on the path of a run
    # without --couch.
    couch_host: str = "127.0.0.1"  # loopback only, never 0.0.0.0: this serves a
    # live video feed of whatever is on the screen
    couch_port: int = 8765
    couch_state_hz: float = 45.0  # JSON state messages per second. The scene
    # interpolates between them, so more than about
    # 60 buys nothing and costs a json.dumps a tick.
    couch_video_fps: float = 30.0  # binary frames per second. Each one is 23 KB,
    # so 30 is 0.7 MB/s over loopback.
    couch_send_timeout: float = 2.0  # seconds a client gets to accept one message
    # before it is dropped. A tab that has been
    # backgrounded to death must not slow the game.
    couch_wait: float = 0.25  # how long a client thread blocks waiting for a new
    # message before looking at the stop flag again
    couch_spike_sample: int = 256  # neurons in the raster. 256 packs to 32 bytes.
    couch_spike_per_pool: int = 8  # of those, how many come from each motor pool
    couch_event_limit: int = 96  # press events buffered between two state
    # messages, so a wedged sender cannot grow a list
    couch_pace_hz: float = 60.0  # PyBoy's null window does not limit speed, so the
    # loop paces itself here. Measured without it:
    # about 1,400 ticks/s headless, 23x too fast to watch.
    # `run.py --record`: headless Edge renders the scene, the frames come
    # over CDP's Page.startScreencast and go into an mp4 (`record.py`).
    # Named couch_* so none of them is in the dynamics fingerprint.
    couch_record_fps: int = 60  # frames per second in the file
    couch_record_seconds: float = 20.0  # a take's length with no --seconds
    couch_record_tail: float = 5.0  # a replay's take runs this long after the
    # milestone lands, so the flash is in it
    couch_record_quality: int = 90  # the browser's JPEG quality per frame
    couch_record_crf: int = 23  # libx264's constant rate factor: lower is
    # better and bigger. Measured on 10 s takes of the fly close-up at
    # 1080x1920/60: crf 18 9.6 MB/s, 20 6.8, 21 5.1, 22 3.3, 23 1.7. The
    # scene's film grain is what the low numbers spend their bits on; 23
    # keeps every edge and smooths the grain.
    couch_record_min_fps: float = 50.0  # a capture rate under this is
    # reported loudly: a 60 fps file made of fewer captures stutters
    couch_record_lead: float = 0.15  # seconds between the first game frame
    # going to the page and the take starting, so a take does not open on the
    # TV's static (measured: without it the first frame of every take was)
    couch_record_ready_timeout: float = 40.0  # seconds for the browser to
    # start, load the scene and boot it before the take is abandoned
    couch_record_stall: float = 3.0  # seconds past the take's end, by the
    # wall clock, before a page that stopped repainting ends the take
    couch_record_backlog: int = 600  # screencast frames held waiting for the
    # encoder (about 0.4 MB each) before new ones are dropped and counted

    # ---- hud ------------------------------------------------------------
    hud_every: int = 6  # ticks between HUD redraws
    hud_history: int = 8  # actions kept in the "last actions" strip
    hud_bar_width: int = 20  # characters in an activation bar

    # ---- mushroom body --------------------------------------------------
    # The learned part. Static 16x16 luminance -> sparse Kenyon cells ->
    # one MBON per motor pool plus a value readout, trained by a TD error.
    n_kc: int = 2000  # Kenyon cells in the expansion layer
    kc_claws: int = 7  # input pixels each KC samples. 7 is the real number in
    # the fly; more claws means a less selective code.
    kc_active_frac: float = 0.05  # APL-style global inhibition: only this share of
    # KCs is active per tick, binary. Lower = sparser,
    # more selective, slower to generalise.
    mbon_gain: float = 0.060  # peak current a fully saturated MBON injects into
    # every neuron of its pool. Sized against the
    # retinotopic pathway (w_bias_out 0.055 x 24 cells):
    # enough to tilt a pool, never enough to pin it.
    mbon_scale: float = 1.0  # divisor inside the tanh. mbon is a sum over ~100
    # active KCs, so without this the squash saturates
    # after a handful of updates and the bias is binary.
    gamma: float = 0.997  # TD discount PER TICK. 0.997 is a horizon of ~330
    # ticks, about 5 seconds of game time.
    lambda_actor: float = 0.96  # actor eligibility decay per tick (tau ~25 ticks).
    # Must span press -> the game finishing the step
    # that press caused, which is 10 to 20 ticks.
    lambda_critic: float = 0.98  # critic eligibility decay per tick (tau ~50)
    lr_actor: float = 0.0020  # actor learning rate. See the arithmetic below: the
    # effective step on an MBON is roughly this times
    # `n_kc_active` times the trace's own sum.
    lr_critic: float = 0.00005  # critic learning rate. This looks absurdly small and
    # it is not. An update writes to all `n_kc_active`
    # = 100 active KCs at once, and a critic trace whose
    # KC keeps being active saturates at 1/(1-lambda) =
    # 50, so the step on the value readout is about
    # 100 * 50 = 5000 times this number. At the obvious
    # 0.002 the value estimate oscillates by tens per
    # tick, the TD error is then noise, and the actor
    # random-walks into its clip with the wrong sign:
    # measured, that gave LEFT the MOST negative weight
    # in the context where LEFT was the only thing that
    # paid. This is the single most sensitive number in
    # the learning half of the project.
    w_actor_clip: float = 0.050  # per-synapse bound on the KC->MBON weights. 100 active
    # KCs, so a saturated MBON is +-5 and the tanh below
    # is hard over. Raise this and nothing changes; lower
    # it and the bias goes gradual.
    w_critic_clip: float = 0.200  # per-synapse bound on the KC->value weights, so the
    # value estimate is bounded by +-20. It has to be
    # above the real return (about 14 in the two-context
    # test world) or the critic sits on its clip and the
    # TD error never settles.
    reward_scale: float = 1.0  # every reward part is divided by this before the TD
    # error, for keeping the critic in a sane range
    lr_decay_episodes: float = 100.0  # learning-rate schedule, both readouts:
    # lr = lr0 / (1 + episodes_trained / this). The count
    # is the brain's own, saved with it, so a resumed run
    # continues the schedule: at 100 episodes the rate is
    # half, at 300 a quarter. Measured reason: at a
    # constant rate, 129 more episodes from the 100-episode
    # brain wandered in and out of the policy it had found
    # (leave-house share 1.00 down to 0.00 and back, by
    # 10-episode bucket), because one coin flip (did it
    # get out the door) dominates each episode's reward.
    # 0 switches the schedule off.

    # ---- reward ---------------------------------------------------------
    # Every address below was checked against the pret/pokered symbol file
    # (github.com/pret/pokered, `symbols` branch, pokered.sym, read 2026-09-20).
    # The pokered symbol name is in the comment. Nothing here is from memory.
    party_count_addr: int = 0xD163  # wPartyCount
    party_level_addr: int = 0xD18C  # wPartyMon1Level
    party_stride: int = 0x2C  # wPartyMon2Level (0xD1B8) - wPartyMon1Level
    badges_addr: int = 0xD356  # wObtainedBadges, one bit per badge
    event_flags_addr: int = 0xD747  # wEventFlags, start of the flag array
    event_flags_end: int = 0xD887  # exclusive: the next symbol is wGrassRate
    player_name_addr: int = 0xD158  # wPlayerName, first character
    joy_ignore_addr: int = 0xCD6B  # wJoyIgnore, nonzero while the engine is
    # swallowing input (cutscene, map transition)
    # For the milestones. pret/pokered `ram/wram.asm` (read 2026-09-22) lays out
    # "Party Data" as wPartyCount db, wPartySpecies ds PARTY_LENGTH + 1, then
    # wPartyMons, six `party_struct`s. So wPartySpecies is wPartyCount + 1 and
    # wPartyMon1 is wPartyCount + 8 = 0xD16B. The struct's field offsets
    # (species db, HP dw, level db, status db, two types, catch rate, four
    # moves, OT id dw, exp ds 3, ...) are checked against the verified
    # wPartyMon1Level above: species 0, HP 1, exp 0x0E, level 0x21, and
    # 0xD16B + 0x21 is exactly 0xD18C.
    party_species_addr: int = 0xD164  # wPartySpecies, one byte per member, $FF ends it
    party_hp_addr: int = 0xD16C  # wPartyMon1HP, two bytes big endian
    party_exp_addr: int = 0xD179  # wPartyMon1Exp, three bytes big endian

    reward_tile: float = 1.0  # first visit to a (map, x, y) this episode
    reward_map: float = 5.0  # first entry to a map id this episode. A second
    # visit pays nothing, so the stairs cannot be farmed.
    reward_event: float = 3.0  # per newly set event-flag bit
    reward_level: float = 5.0  # per level gained across the party
    reward_badge: float = 50.0  # per new badge

    # ---- training -------------------------------------------------------
    train_ticks: int = 2_000_000  # total tick budget for `train.py`
    episode_ticks: int = 20_000  # ticks per episode
    eval_every: int = 10  # training episodes between evaluation blocks
    eval_block: int = 6  # learning-off episodes per evaluation block; the block
    # score is their mean reward. Measured: one block
    # episode's reward has sd 58.5, so a 3-episode mean is
    # uncertain by ~34 and picking the maximum of 16 such
    # scores kept a brain worse on the held-out seeds than
    # the one it started from. 6 halves the variance.
    best_margin: float = 25.0  # a block replaces the best brain only when its score
    # beats the incumbent's by at least this much. About one
    # standard error of a 6-episode block (58.5 / sqrt(6)).
    eval_block_seed: int = 8_000_000  # block episode i uses seed + this + i, the
    # SAME seeds every block, so scores are comparable across
    # blocks. Clear of the training seeds (seed + 1000 * ep)
    # and the held-out 90000-90009 set.
    checkpoint_every: int = 10  # episodes between training-state checkpoints
    training_state_path: Path = Path("brains/training.npz")  # latest weights; `--resume` reads it
    best_brain_path: Path = Path("brains/latest.npz")  # best block score; `run.py` loads it
    start_state_path: Path = Path("states/bedroom.state")
    train_log_path: Path = Path("runs/train.csv")

    # ---- milestones, replay and the journey -------------------------------
    game_hz: int = 60  # emulator ticks per second of game time
    milestone_dir: Path = Path("milestones")  # journey.json and one folder of
    # replay files per milestone. run.py and train.py point it at the repo;
    # the library functions record nothing unless handed a recorder.
    snapshot_every: int = 300  # ticks between the rolling buffer's fly snapshots
    # (five seconds). Each costs well under a millisecond: the
    # emulator half is a reference to the last anchor plus
    # the buttons pressed since (see `emulator.py`).
    replay_lead: int = 900  # how far before a milestone its replay starts (15 s)
    anchor_every: int = 18_000  # ticks between full emulator savestates (five
    # minutes of game). One costs about 20 ms through
    # PyBoy's per-byte writer, which is why it is not taken
    # every snapshot. A replay fast-forwards at most this
    # many ticks of recorded input, about 3 s at 6,400
    # ticks/s. Lower it for faster replays, raise it for
    # fewer hitches.
    journey_dir: Path = Path("saves/journey")  # the journey save
    autosave_minutes: float = 5.0  # wall-clock minutes between journey autosaves
    journey_episode_ticks: int = 216_000  # a journey brain's `episodes_trained`
    # advances once per this many learning ticks (an hour
    # of game time), so the learning-rate schedule keeps
    # decaying while you watch.

    # ---- emulator -------------------------------------------------------
    map_id_addr: int = 0xD35E  # Pokemon Red: current map id (wCurMap)
    player_y_addr: int = 0xD361  # Pokemon Red: player Y tile (wYCoord)
    player_x_addr: int = 0xD362  # Pokemon Red: player X tile (wXCoord)
    in_battle_addr: int = 0xD057  # Pokemon Red: nonzero in battle (wIsInBattle)

    # ---- derived --------------------------------------------------------
    pool_names: tuple[str, ...] = field(default=POOL_NAMES)

    @property
    def n_sensory(self) -> int:
        """Two channels (ON and OFF) per downsampled pixel."""
        return 2 * self.retina_size * self.retina_size

    @property
    def n_motor(self) -> int:
        return self.pool_size * len(self.pool_names)

    @property
    def n_kc_active(self) -> int:
        """How many Kenyon cells survive the APL inhibition each tick."""
        return max(1, int(round(self.kc_active_frac * self.n_kc)))


# Config fields that change how a run is shown, how long it is or where its
# files go, and never what the next tick does. Everything else is in the
# fingerprint a fly snapshot carries: restoring a snapshot into a fly built
# from different numbers would not repeat anything.
_NOT_DYNAMICS: frozenset[str] = frozenset(
    {
        "rom_path",
        "headless",
        "uncapped",
        "hud",
        "max_steps",
        "load_state",
        "save_state",
        "train_ticks",
        "episode_ticks",
        "eval_every",
        "eval_block",
        "best_margin",
        "eval_block_seed",
        "checkpoint_every",
        "training_state_path",
        "best_brain_path",
        "start_state_path",
        "train_log_path",
        "game_hz",
        "milestone_dir",
        "snapshot_every",
        "replay_lead",
        "anchor_every",
        "journey_dir",
        "autosave_minutes",
    }
)


def dynamics_fingerprint(cfg: Config) -> str:
    """A short hash of every number that decides what the next tick does."""
    import hashlib
    import json
    from dataclasses import fields as dataclass_fields

    values = {}
    for item in dataclass_fields(cfg):
        name = item.name
        if name in _NOT_DYNAMICS or name.startswith(("couch_", "hud_")):
            continue
        value = getattr(cfg, name)
        values[name] = str(value) if isinstance(value, Path) else value
    text = json.dumps(values, sort_keys=True, default=repr)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
