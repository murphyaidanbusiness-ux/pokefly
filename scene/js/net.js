/**
 * The feed from the Python side, and the one pure function that reads it.
 *
 * `decodeMessage` touches nothing outside its argument: a string or some bytes
 * in, a plain object out. It is the only part of the client the protocol can
 * break, so it is the part worth being able to call from anywhere.
 *
 * `Feed` is the socket around it: it connects, hands decoded messages to the
 * callbacks, and reconnects by itself when the run ends or the server is
 * restarted.
 */

export const PROTOCOL_VERSION = 2;

/** First byte of a binary message: a raw 160x144 grayscale video frame. */
export const VIDEO_MESSAGE = 1;

/**
 * @param {string|ArrayBuffer|Uint8Array} data one websocket message
 * @returns {{kind:string}} one of
 *   {kind:'hello', hello}  {kind:'state', state}  {kind:'status', status}
 *   {kind:'video', pixels} {kind:'unknown', type} {kind:'error', reason}
 */
export function decodeMessage(data) {
  if (typeof data === 'string') {
    let parsed;
    try {
      parsed = JSON.parse(data);
    } catch (err) {
      return { kind: 'error', reason: 'the state message was not JSON: ' + err.message };
    }
    if (parsed === null || typeof parsed !== 'object') {
      return { kind: 'error', reason: 'the state message was not an object' };
    }
    if (parsed.type === 'hello') return { kind: 'hello', hello: parsed };
    if (parsed.type === 'state') return { kind: 'state', state: parsed };
    if (parsed.type === 'status') return { kind: 'status', status: parsed };
    return { kind: 'unknown', type: parsed.type === undefined ? null : parsed.type };
  }
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  if (bytes.length < 1) return { kind: 'error', reason: 'an empty binary message' };
  if (bytes[0] !== VIDEO_MESSAGE) return { kind: 'unknown', type: bytes[0] };
  return { kind: 'video', pixels: bytes.subarray(1) };
}

/** The spike sample arrives packed eight neurons to a byte, first neuron in
 *  the high bit, which is what numpy's packbits writes. */
export function unpackBits(encoded, count) {
  const out = new Uint8Array(count);
  if (!encoded) return out;
  let binary;
  try {
    binary = atob(encoded);
  } catch {
    return out;
  }
  for (let i = 0; i < count; i += 1) {
    const byte = binary.charCodeAt(i >> 3);
    if (Number.isNaN(byte)) break;
    out[i] = (byte >> (7 - (i & 7))) & 1;
  }
  return out;
}

export class Feed {
  /**
   * @param {object} handlers {onHello, onState, onVideo, onStatus, onRunStatus}
   *   onStatus is the connection (connecting / connected / disconnected);
   *   onRunStatus is the server's `status` message (paused, saved_ago).
   */
  constructor(handlers = {}) {
    this.handlers = handlers;
    this.socket = null;
    this.status = 'connecting';
    this.closed = false;
    this.retryIn = 500;
    this.counts = { hello: 0, state: 0, status: 0, video: 0, bad: 0, sent: 0 };
  }

  get url() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/ws`;
  }

  start() {
    if (this.closed) return;
    this._setStatus('connecting');
    let socket;
    try {
      socket = new WebSocket(this.url);
    } catch (err) {
      this._retry('could not open a websocket: ' + err.message);
      return;
    }
    socket.binaryType = 'arraybuffer';
    this.socket = socket;
    socket.onopen = () => {
      this.retryIn = 500;
      this._setStatus('connected');
    };
    socket.onmessage = (event) => this._message(event.data);
    socket.onerror = () => {};
    socket.onclose = () => this._retry('the run ended or the server went away');
  }

  stop() {
    this.closed = true;
    if (this.socket) this.socket.close();
  }

  /**
   * One command to the run: 'save' or 'pause'. The server ignores anything
   * else. Returns false when there is no open socket to send it on.
   */
  command(name) {
    const socket = this.socket;
    if (!socket || socket.readyState !== 1) return false;
    try {
      socket.send(JSON.stringify({ cmd: name }));
      this.counts.sent += 1;
      return true;
    } catch {
      return false;
    }
  }

  _message(data) {
    const message = decodeMessage(data);
    if (message.kind === 'hello') {
      this.counts.hello += 1;
      this.handlers.onHello?.(message.hello);
    } else if (message.kind === 'state') {
      this.counts.state += 1;
      this.handlers.onState?.(message.state);
    } else if (message.kind === 'status') {
      this.counts.status += 1;
      this.handlers.onRunStatus?.(message.status);
    } else if (message.kind === 'video') {
      this.counts.video += 1;
      this.handlers.onVideo?.(message.pixels);
    } else {
      this.counts.bad += 1;
    }
  }

  _setStatus(status, detail = '') {
    this.status = status;
    this.handlers.onStatus?.(status, detail);
  }

  _retry(reason) {
    if (this.closed) return;
    this.socket = null;
    this._setStatus('disconnected', reason);
    const wait = this.retryIn;
    this.retryIn = Math.min(this.retryIn * 1.6, 5000);
    setTimeout(() => this.start(), wait);
  }
}
