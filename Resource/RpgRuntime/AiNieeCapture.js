/* Optional diagnostic capture for explicitly requested TEST OUTPUT copies. */
(() => {
  'use strict';
  const MAX = 3000, RATE = 100;
  const capture = {enabled: true, build_id: '', events: [], dropped: 0,
    duplicates: 0, rate_limited: 0, evicted: 0};
  const seen = new Set(), keys = [];
  let depth = 0, period = 0, accepted = 0;
  capture.drain = () => { const rows = capture.events.splice(0); seen.clear(); keys.length = 0; return rows; };
  capture.stop = () => { capture.enabled = false; clearInterval(timer); };
  capture.exportJSON = () => JSON.stringify({schema_version: 1, build_id: capture.build_id,
    enabled: capture.enabled, events: capture.events, dropped: capture.dropped,
    duplicates: capture.duplicates, rate_limited: capture.rate_limited, evicted: capture.evicted,
    max_events: MAX, max_events_per_second: RATE});
  window.AiNieeCapture = capture;
  function record(text, sink, owner, maxWidth, x, y) {
    if (!capture.enabled || typeof text !== 'string' || !/[\u3040-\u30ff\u3400-\u9fff]/.test(text)) return;
    const characters = text.length > 4096 ? Array.from(text) : null;
    const truncated = !!characters && characters.length > 4096;
    const map = window.$gameMap, interpreter = map && map._interpreter;
    const bitmap = owner && (owner.contents || owner);
    const right = bitmap && Number.isFinite(bitmap.width) && Number.isFinite(x) ? Math.max(0, bitmap.width - x) : null;
    // RPG Maker treats zero as its default width rather than an empty area.
    const requested = Number.isFinite(maxWidth) && maxWidth !== 0 ? maxWidth : null;
    const row = {text: truncated ? characters.slice(0, 4096).join('') : text, sink,
      window_class: owner && owner.constructor ? owner.constructor.name : '',
      window_id: owner && owner._data && typeof owner._data.Id === 'string' ? owner._data.Id : '',
      window_x: owner && owner.contents && Number.isFinite(owner.x) ? owner.x : null,
      window_y: owner && owner.contents && Number.isFinite(owner.y) ? owner.y : null,
      scene: window.SceneManager && SceneManager._scene ? SceneManager._scene.constructor.name : '',
      map_id: map && typeof map.mapId === 'function' ? map.mapId() : 0,
      event_id: interpreter ? interpreter._eventId || 0 : 0,
      command_index: interpreter ? interpreter._index || 0 : 0,
      max_width: Number.isFinite(maxWidth) ? maxWidth : null,
      available_width: right === null ? requested : requested === null ? right : Math.min(right, requested),
      x: Number.isFinite(x) ? x : null, y: Number.isFinite(y) ? y : null,
      font_family: bitmap && typeof bitmap.fontFace === 'string' ? bitmap.fontFace : '',
      entry_pixel_size: bitmap && Number.isFinite(bitmap.fontSize) ? bitmap.fontSize : null,
      logical_line_count: text.split(/\r\n|\r|\n/).length,
      truncated, time_ms: Date.now()};
    const key = JSON.stringify([row.text, row.scene, row.map_id, row.event_id,
      row.command_index, sink, row.window_class, row.window_id, row.window_x, row.window_y,
      row.x, row.y, row.available_width, row.font_family, row.entry_pixel_size]);
    if (seen.has(key)) { capture.duplicates++; return; }
    if (row.time_ms - period >= 1000 || row.time_ms < period) { period = row.time_ms; accepted = 0; }
    if (accepted >= RATE) { capture.rate_limited++; capture.dropped++; return; }
    accepted++;
    if (capture.events.length === MAX) {
      capture.events.shift(); seen.delete(keys.shift()); capture.evicted++; capture.dropped++;
    }
    seen.add(key); keys.push(key); capture.events.push(row); return row;
  }
  function wrap(owner, name, sink, widthIndex) {
    const original = owner[name];
    owner[name] = function(text) {
      const row = !depth ? record(text, sink, this, arguments[widthIndex], arguments[1], arguments[2]) : null;
      depth++;
      try {
        const result = original.apply(this, arguments);
        if (row && Number.isFinite(result)) {
          row.measured_width = result; row.measurement = 'drawTextEx-return';
          row.exit_pixel_size = this.contents && this.contents.fontSize;
        }
        return result;
      }
      finally { depth--; }
    };
  }
  let attempts = 0;
  const timer = setInterval(() => {
    if (!capture.enabled || ++attempts > 200) { clearInterval(timer); return; }
    if (!window.Bitmap || !Bitmap.prototype.drawText || !window.Window_Base ||
        !Window_Base.prototype.drawTextEx || !window.Window_Message) return;
    clearInterval(timer);
    wrap(Window_Base.prototype, 'drawTextEx', 'Window_Base.drawTextEx', 3);
    const start = Window_Message.prototype.startMessage;
    Window_Message.prototype.startMessage = function() {
      record($gameMessage.allText(), 'Window_Message.startMessage', this, this.contents && this.contents.width);
      depth++;
      try { return start.apply(this, arguments); }
      finally { depth--; }
    };
    const update = Window_Message.prototype.updateMessage;
    Window_Message.prototype.updateMessage = function() {
      depth++;
      try { return update.apply(this, arguments); }
      finally { depth--; }
    };
    const original = Bitmap.prototype.drawText;
    Bitmap.prototype.drawText = function(text, x, y, maxWidth, lineHeight, align) {
      const row = !depth ? record(text, 'Bitmap.drawText', this, maxWidth, x, y) : null;
      if (row) { row.measured_width = this.measureTextWidth(text); row.measurement = 'canvas-natural-width'; }
      return original.apply(this, arguments);
    };
  }, 250);
})();
