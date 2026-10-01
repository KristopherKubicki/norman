/* Account-scoped navigation preferences and connection labels. */
(() => {
  const identity = c => c.kind === 'direct'
    ? `direct:${c.principal_slug}:${c.direct_agent_slug}` : `room:${c.conversation_id}`;
  function createPreferences(owner, storage = window.localStorage) {
    const key = `norman-chat-navigation:${owner || 'anonymous'}`;
    let prefs = { pins: [], visits: {} };
    try {
      const saved = JSON.parse(storage.getItem(key) || 'null');
      if (saved) prefs = {
        pins: Array.isArray(saved.pins) ? saved.pins.filter(x => typeof x === 'string').slice(0, 20) : [],
        visits: Object.fromEntries(Object.entries(saved.visits || {}).filter(([k,v]) => k && Number.isFinite(v)).slice(-100)),
      };
    } catch (_) { /* Navigation works without browser storage. */ }
    const persist = () => { try { if (owner) storage.setItem(key, JSON.stringify(prefs)); } catch (_) {} };
    return {
      pinned: c => prefs.pins.includes(identity(c)),
      toggle(c) {
        const id = identity(c);
        prefs.pins = prefs.pins.includes(id) ? prefs.pins.filter(x => x !== id) : [...prefs.pins.slice(-19), id];
        persist();
      },
      visit(c) {
        prefs.visits[identity(c)] = Date.now();
        prefs.visits = Object.fromEntries(Object.entries(prefs.visits).sort((a,b) => b[1]-a[1]).slice(0,100));
        persist();
      },
      list(conversations, search = '') {
        return conversations.filter(c => `${c.title || ''} ${c.direct_agent_slug || ''} ${c.principal_slug || ''}`.toLowerCase().includes(search.toLowerCase()))
          .sort((a,b) => Number(prefs.pins.includes(identity(b))) - Number(prefs.pins.includes(identity(a)))
            || (prefs.visits[identity(b)] || Date.parse(b.updated_at) || 0) - (prefs.visits[identity(a)] || Date.parse(a.updated_at) || 0))
          .filter((c,i) => prefs.pins.includes(identity(c)) || i < 10);
      },
    };
  }
  function connectionLabel({ online, authenticated, connected, failed }) {
    if (!online) return { label: 'Offline', tone: 'warn', detail: 'Your device is offline. Drafts are kept on this device.' };
    if (!authenticated) return { label: 'Sign in', tone: 'warn', detail: 'Sign in to connect your chats.' };
    if (failed) return { label: 'Reconnecting', tone: 'warn', detail: 'Could not reach Norman. Saved chats remain available.' };
    if (!connected) return { label: 'Connecting', tone: 'watch', detail: 'Checking the connection to Norman.' };
    return { label: 'Connected', tone: 'ok', detail: 'Connected to Norman. Individual bots may have their own status.' };
  }
  window.BridgeNavigation = { createPreferences, connectionLabel };
})();
