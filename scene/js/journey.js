/**
 * The journey on screen: the milestone strip, the milestone flash, the replay
 * countdown, and the Save and Pause buttons.
 *
 * All DOM, no three.js. Every number comes from a state or status message;
 * the only thing computed here is how long ago the last save was, counted on
 * from the last value the server sent so it keeps ticking while paused.
 *
 * The strip reads, left to right: the last milestone and when it landed, a
 * live game-time timer since it, and the brain's generation (its
 * episodes_trained). In portrait it is the bottom of the frame and also holds
 * the compact status bar; in landscape it is a bar along the bottom.
 */

const FLASH_SECONDS = 3.0;

function clock(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = whole % 60;
  const mm = hours ? String(minutes).padStart(2, '0') : String(minutes);
  return (hours ? `${hours}:` : '') + `${mm}:${String(secs).padStart(2, '0')}`;
}

export class JourneyPanel {
  /**
   * @param {HTMLElement} root the #strip element
   * @param {HTMLElement} flash the #flash element
   * @param {object} actions {save(), pause()} what the buttons do
   */
  constructor(root, flash, actions) {
    this.root = root;
    this.flashBox = flash;
    this.actions = actions;
    const cell = (id) => document.getElementById(id);
    this.cells = {
      last: cell('s-last'),
      lastAt: cell('s-last-at'),
      since: cell('s-since'),
      gen: cell('s-gen'),
      brain: cell('s-brain'),
      countdown: cell('s-countdown'),
      game: cell('s-game'),
      saved: cell('s-saved'),
      where: cell('s-where'),
      feed: cell('s-feed'),
      flashName: cell('f-name'),
      flashTime: cell('f-time'),
    };
    this.saveButton = cell('b-save');
    this.pauseButton = cell('b-pause');
    this.saveButton.addEventListener('click', () => this.save());
    this.pauseButton.addEventListener('click', () => this.pause());

    this.gameHz = 60;
    this.journey = false;
    this.paused = false;
    this.savedAgo = null; // seconds, as of savedAt
    this.savedAt = 0; // performance.now() when savedAgo arrived
    this.saving = false;
    this.flashLeft = 0;
    this.onFlash = null; // set by main.js: the gold pulse on the fly's head
  }

  setHello(hello) {
    this.gameHz = hello.game_hz || 60;
  }

  // -- the page's side -------------------------------------------------------

  save() {
    if (!this.journey) return;
    if (this.actions.save()) {
      this.saving = true;
      this.cells.saved.textContent = 'saving...';
    } else {
      this.cells.saved.textContent = 'not connected';
    }
  }

  pause() {
    this.actions.pause();
  }

  // -- the feed's side -------------------------------------------------------

  setState(state) {
    for (const landed of state.milestones || []) this.flash(landed);

    const last = state.last_milestone;
    this.cells.last.textContent = last ? last.label : 'nothing yet';
    this.cells.lastAt.textContent = last ? `at ${last.game_time} of game time` : 'the journey so far';
    this.cells.since.textContent = '+' + (state.since_time || '0:00');
    this.cells.gen.textContent = `generation ${state.generation ?? 0}`;
    this.cells.brain.textContent = state.brain_file || '';
    this.cells.game.textContent = state.game_time || '';
    this.cells.where.textContent = `${state.map_name}` + (state.in_battle ? ', in a battle' : '');

    const countdown = state.countdown;
    this.cells.countdown.hidden = !countdown;
    if (countdown) this.cells.countdown.textContent = countdown.text;

    this._runStatus(state);
  }

  setRunStatus(status) {
    this._runStatus(status);
  }

  setFeed(status) {
    const words = { connected: 'live', connecting: 'connecting', disconnected: 'not connected' };
    this.cells.feed.textContent = words[status] || status;
    this.cells.feed.dataset.state = status;
  }

  _runStatus(status) {
    if (status.journey !== undefined) this.journey = Boolean(status.journey);
    if (status.paused !== undefined) this.paused = Boolean(status.paused);
    if (status.saved_ago !== undefined) {
      const before = this.savedAgo;
      this.savedAgo = status.saved_ago;
      this.savedAt = performance.now();
      if (this.saving && status.saved_ago !== null && (before === null || status.saved_ago < before)) {
        this.saving = false;
      }
    }
    this.saveButton.hidden = !this.journey;
    this.pauseButton.textContent = this.paused ? 'Resume' : 'Pause';
    this.root.dataset.paused = this.paused ? 'yes' : 'no';
  }

  // -- the flash -------------------------------------------------------------

  flash(landed) {
    this.cells.flashName.textContent = landed.label;
    this.cells.flashTime.textContent = `${landed.game_time} of game time`;
    const box = this.flashBox;
    box.hidden = false;
    // Restart the CSS animation even if a flash is already showing.
    box.classList.remove('on');
    void box.offsetWidth;
    box.classList.add('on');
    this.flashLeft = FLASH_SECONDS;
    if (this.onFlash) this.onFlash(landed);
  }

  update(dt) {
    if (this.flashLeft > 0) {
      this.flashLeft -= dt;
      if (this.flashLeft <= 0) {
        this.flashBox.classList.remove('on');
        this.flashBox.hidden = true;
      }
    }
    if (this.saving) return;
    if (!this.journey) {
      this.cells.saved.textContent = '';
    } else if (this.savedAgo === null) {
      this.cells.saved.textContent = 'not saved yet';
    } else {
      const ago = this.savedAgo + (performance.now() - this.savedAt) / 1000;
      this.cells.saved.textContent = `saved ${clock(ago)} ago`;
    }
  }
}
