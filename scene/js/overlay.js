/**
 * The small DOM panel over the scene. Plain words only: no field names, no
 * units nobody uses out loud. `H` hides it.
 */

const REWARD_PART_WORDS = {
  tile: 'new ground',
  map: 'new place',
  event: 'story flags',
  level: 'levels',
  badge: 'badges',
};

export class Overlay {
  constructor(root) {
    this.root = root;
    this.visible = true;
    this.cell = (id) => root.querySelector(`#${id}`);
    this.fields = {
      status: this.cell('o-status'),
      brain: this.cell('o-brain'),
      where: this.cell('o-where'),
      reward: this.cell('o-reward'),
      firing: this.cell('o-firing'),
      buttons: this.cell('o-buttons'),
      speed: this.cell('o-speed'),
      view: this.cell('o-view'),
      note: this.cell('o-note'),
    };
  }

  toggle() {
    this.visible = !this.visible;
    this.root.style.display = this.visible ? '' : 'none';
    return this.visible;
  }

  setStatus(status, detail = '') {
    const words = {
      connected: 'watching the fly play',
      connecting: 'looking for the game...',
      disconnected: 'not connected' + (detail ? ' (' + detail + ')' : ''),
    };
    this.fields.status.textContent = words[status] || status;
    this.fields.status.dataset.state = status;
  }

  setHello(hello) {
    this.fields.brain.textContent = hello.brain || 'no brain loaded (the untrained fly)';
  }

  setView(name) {
    this.fields.view.textContent = name;
  }

  setNote(text) {
    this.fields.note.textContent = text;
  }

  setState(state) {
    this.fields.where.textContent = `${state.map_name}  x ${state.x}  y ${state.y}` +
      (state.in_battle ? '   in a battle' : '');
    const parts = Object.entries(state.parts || {})
      .filter(([, value]) => value > 0)
      .map(([name, value]) => `${Math.round(value)} from ${REWARD_PART_WORDS[name] || name}`)
      .join(', ');
    this.fields.reward.textContent =
      `${Math.round(state.episode_reward)}` + (parts ? `  (${parts})` : '');
    this.fields.firing.textContent =
      `${(state.firing_rate * 100).toFixed(1)}% of neurons, ${state.panics} startles so far`;
    const recent = (state.history || []).slice(-8).join(' ');
    this.fields.buttons.textContent = recent || 'none yet';
    this.fields.speed.textContent = `${state.tps.toFixed(0)} game frames a second`;
  }
}
