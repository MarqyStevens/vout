/* Shared helpers: resilient WebSocket + visibilitychange resync + server clock offset */

window.VoutCommon = (() => {
  let clockOffsetMs = 0;

  function syncClock(serverTimeIso) {
    if (!serverTimeIso) return;
    const srv = Date.parse(serverTimeIso);
    if (!Number.isNaN(srv)) {
      clockOffsetMs = srv - Date.now();
    }
  }

  function serverNowMs() {
    return Date.now() + clockOffsetMs;
  }

  function remainingSeconds(vote) {
    if (!vote || vote.status !== 'open' || !vote.closes_at) return null;
    const closes = Date.parse(vote.closes_at);
    if (Number.isNaN(closes)) return null;
    return Math.max(0, (closes - serverNowMs()) / 1000);
  }

  function esc(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showToast(msg, isError = false) {
    const existing = document.getElementById('vout-toast');
    if (existing) existing.remove();
    const el = document.createElement('div');
    el.id = 'vout-toast';
    el.className = 'toast' + (isError ? ' error' : '');
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => { if (el.parentNode) el.remove(); }, 3200);
  }

  function choiceLabelSk(choice) {
    const map = {
      for: 'ZA',
      against: 'PROTI',
      abstain: 'ZDRŽAL SA',
      not_voted: 'NEHLASOVAL',
      absent: 'NEPRÍTOMNÝ',
    };
    return map[choice] || choice || '—';
  }

  async function apiJson(url, opts = {}) {
    const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    const res = await fetch(url, Object.assign({}, opts, { headers }));
    let data = null;
    const text = await res.text();
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = { detail: text }; }
    if (!res.ok) {
      const msg = (data && data.detail) ? data.detail : `Chyba ${res.status}`;
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function createResilientSocket({ wsPath, onState, onStatus, resyncFn }) {
    let ws = null;
    let closedByUser = false;
    let retryMs = 1000;
    let pingTimer = null;

    function buildUrl() {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${proto}//${location.host}${wsPath}`;
    }

    function connect() {
      if (closedByUser) return;
      try {
        ws = new WebSocket(buildUrl());
      } catch (_) {
        scheduleReconnect();
        return;
      }
      ws.onopen = () => {
        retryMs = 1000;
        if (onStatus) onStatus(true);
        clearInterval(pingTimer);
        pingTimer = setInterval(() => {
          if (ws && ws.readyState === WebSocket.OPEN) ws.send('ping');
        }, 20000);
      };
      ws.onmessage = (ev) => {
        if (ev.data === 'pong') return;
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'state' && msg.data) {
            syncClock(msg.data.server_time);
            onState(msg.data);
          }
        } catch (_) {}
      };
      ws.onclose = () => {
        clearInterval(pingTimer);
        if (onStatus) onStatus(false);
        scheduleReconnect();
      };
      ws.onerror = () => {
        if (ws) ws.close();
      };
    }

    function scheduleReconnect() {
      if (closedByUser) return;
      setTimeout(() => {
        retryMs = Math.min(retryMs * 1.5, 6000);
        connect();
      }, retryMs);
    }

    async function forceResync() {
      if (resyncFn) {
        try {
          const st = await resyncFn();
          if (st) {
            syncClock(st.server_time);
            onState(st);
          }
        } catch (_) {}
      }
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        connect();
      }
    }

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') forceResync();
    });
    window.addEventListener('online', forceResync);

    connect();
    return {
      close() {
        closedByUser = true;
        clearInterval(pingTimer);
        if (ws) ws.close();
      },
      resync: forceResync,
    };
  }

  return { syncClock, serverNowMs, remainingSeconds, esc, showToast, choiceLabelSk, apiJson, createResilientSocket };
})();
