/* Copyright © 2026 Alen Pepa. */
/* Alen STB shared boundary validation and time utilities. No device simulation. */
(function (root) {
  'use strict';
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const text = (value, name, max = 512) => {
    if (typeof value !== 'string' || !value.trim() || value.length > max) throw Error('Invalid ' + name + '.');
    return value;
  };
  function channels(value) {
    if (!Array.isArray(value) || value.length > 30000) throw Error('Invalid receiver channel list.');
    const ids = new Set();
    return value.map(channel => {
      if (!object(channel)) throw Error('Invalid channel.');
      const id = text(channel.id, 'channel ID', 160);
      if (ids.has(id)) throw Error('Receiver returned duplicate channel IDs.');
      ids.add(id);
      const result = {id, name: text(channel.name, 'channel name', 160)};
      for (const key of ['category', 'program', 'satellite', 'quality', 'logo', 'color']) {
        if (channel[key] !== undefined && channel[key] !== null) {
          if (typeof channel[key] !== 'string' || channel[key].length > 512) throw Error('Invalid channel ' + key + '.');
          result[key] = channel[key];
        }
      }
      for (const key of ['favorite', 'locked']) {
        if (channel[key] !== undefined && typeof channel[key] !== 'boolean') throw Error('Invalid channel ' + key + '.');
        result[key] = channel[key] === true;
      }
      return result;
    });
  }
  function status(value) {
    if (!object(value) || value.protocol !== 'alen-stb-bridge-v1' || !object(value.receiver) ||
        typeof value.receiver.connected !== 'boolean' || !Array.isArray(value.capabilities) ||
        !value.capabilities.every(cap => typeof cap === 'string')) throw Error('Invalid bridge status. Update the local bridge.');
    return value;
  }
  function timers(value) {
    if (!Array.isArray(value)) throw Error('Invalid receiver timers.');
    const ids = new Set();
    return value.map(timer => {
      if (!object(timer)) throw Error('Invalid receiver timer.');
      text(timer.id, 'timer ID', 160);text(timer.title, 'timer title', 120);text(timer.channelId, 'timer channel', 160);
      if (ids.has(timer.id)) throw Error('Duplicate timer ID.');
      ids.add(timer.id);
      if (!Number.isFinite(Date.parse(timer.start)) || !Number.isInteger(timer.duration) || timer.duration < 1 || timer.duration > 1440 ||
          !['Switch channel','Record'].includes(timer.type)) throw Error('Invalid receiver timer fields.');
      return {...timer};
    });
  }
  function settings(value) {
    if (!object(value)) throw Error('Invalid receiver settings.');
    if (value.sleep !== undefined && !['0','15','30','60','120'].includes(String(value.sleep))) throw Error('Unsupported sleep timer value.');
    for (const key of ['parental','screenLock']) if (value[key] !== undefined && typeof value[key] !== 'boolean') throw Error('Invalid receiver setting: ' + key);
    return {...value, sleep: String(value.sleep ?? '0')};
  }
  function localDate(value) {
    const d = new Date(value);
    if (!Number.isFinite(d.getTime())) throw Error('Invalid timer start time.');
    const pad = n => String(n).padStart(2,'0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function timerPayload(fields, id, now = Date.now()) {
    text(fields.title, 'timer title', 120);text(fields.channelId, 'channel', 160);
    const start = new Date(fields.start);
    if (!Number.isFinite(start.getTime()) || start.getTime() <= now) throw Error('Choose a valid start time in the future.');
    const duration = Number(fields.duration);
    if (!Number.isInteger(duration) || duration < 1 || duration > 1440) throw Error('Duration must be 1–1440 whole minutes.');
    if (!['Switch channel','Record'].includes(fields.type)) throw Error('Invalid timer action.');
    return {id, title:fields.title.trim(), channelId:fields.channelId, start:start.toISOString(), duration, type:fields.type};
  }
  function identifier(cryptoProvider = root.crypto) {
    if (typeof cryptoProvider?.randomUUID === 'function') return cryptoProvider.randomUUID();
    if (!cryptoProvider?.getRandomValues) throw Error('This browser cannot generate a secure timer identifier.');
    const bytes = cryptoProvider.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(b=>b.toString(16).padStart(2,'0')).join('');
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  function streamUrl(raw, base) {
    text(raw, 'stream URL', 8192);
    const url = base ? new URL(raw, base) : new URL(raw);
    if (!['http:','https:'].includes(url.protocol) || url.username || url.password) throw Error('Use an HTTP(S) stream URL without embedded credentials.');
    return url;
  }
  class Session {
    constructor() { this.epoch = 0; this.controllers = new Set(); }
    reset() { this.epoch++; for (const controller of this.controllers) controller.abort();this.controllers.clear(); }
    async run(task, timeout = 9000) {
      const epoch = this.epoch;
      const controller = new AbortController();this.controllers.add(controller);
      const timer = setTimeout(()=>controller.abort(),timeout);
      try {
        const result = await task(controller.signal);
        if (epoch !== this.epoch) throw new Error('Connection changed; stale response ignored.');
        return result;
      } finally {clearTimeout(timer);this.controllers.delete(controller);}
    }
  }
  const exported = {object,channels,status,timers,settings,localDate,timerPayload,identifier,streamUrl,Session};
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  else root.AlenCore = exported;
})(typeof globalThis !== 'undefined' ? globalThis : this);
