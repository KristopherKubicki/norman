/* Bounded, account-scoped tab cache. Cached data never authorizes a request. */
(() => {
  window.createBridgeCache = (owner, storage = window.sessionStorage) => {
    const key = 'norman-bridge-snapshots-v1';
    const maxAge = 30 * 60 * 1000;
    const maxSize = 1500000;
    let entries = {};
    try {
      const saved = JSON.parse(storage.getItem(key) || 'null');
      if (owner && saved?.owner === owner) entries = saved.entries || {};
      else storage.removeItem(key);
    } catch (_) { /* Storage is optional, including in private browsing. */ }
    const persist = () => {
      try {
        storage.setItem(key, JSON.stringify({ owner, entries }));
      } catch (_) { /* A full tab cache must not prevent live loading. */ }
    };
    return {
      get(name) {
        if (!owner) return null;
        const entry = entries[name];
        if (!entry || !Number.isFinite(entry.at) || Date.now() - entry.at > maxAge || entry.at > Date.now()) return null;
        return entry.value;
      },
      set(name, value) {
        if (!owner) return;
        try {
          if (JSON.stringify(value).length > maxSize / 2) return;
          entries[name] = { at: Date.now(), value };
          const names = Object.keys(entries).sort((a, b) => entries[a].at - entries[b].at);
          while (names.length > 8 || JSON.stringify(entries).length > maxSize) {
            delete entries[names.shift()];
          }
          persist();
        } catch (_) { /* Ignore non-serializable responses. */ }
      },
      clear() {
        entries = {};
        try { storage.removeItem(key); } catch (_) { /* Optional storage. */ }
      },
    };
  };
})();
