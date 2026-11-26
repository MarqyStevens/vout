/* /admin — Secretary / Chair full control panel */

(() => {
  const { esc, apiJson, showToast, choiceLabelSk, remainingSeconds, createResilientSocket } = window.VoutCommon;

  let adminPin = sessionStorage.getItem('vout_admin_pin') || '';
  let sessions = [];
  let state = null;
  let activeTab = 'agenda';
  let selectedDuration = 15;
  let socket = null;
  let auditLogs = [];

  const loginWrap = document.getElementById('admin-login-wrap');
  const appWrap = document.getElementById('admin-app');

  function adminHeaders() {
    return { 'X-Admin-Pin': adminPin };
  }

  async function adminApi(url, opts = {}) {
    return apiJson(url, Object.assign({}, opts, { headers: Object.assign(adminHeaders(), opts.headers || {}) }));
  }

  async function loadAdminState(sessionId = null) {
    const q = sessionId ? `?session_id=${sessionId}` : '';
    const data = await adminApi(`/api/admin/state${q}`);
    sessions = data.sessions || [];
    state = data.state;
    if (state && state.session) {
      selectedDuration = state.session.default_duration_sec ?? 15;
    }
    renderAll();
    if (activeTab === 'audit') loadAudit();
  }

  async function loadAudit() {
    if (!state || !state.session) return;
    try {
      auditLogs = await adminApi(`/api/admin/sessions/${state.session.id}/audit?limit=150`);
      renderAuditTab();
    } catch (_) {}
  }

  function startSocket() {
    if (socket) socket.close();
    socket = createResilientSocket({
      wsPath: `/ws/admin?pin=${encodeURIComponent(adminPin)}`,
      onState(newState) {
        state = newState;
        renderAll();
        if (activeTab === 'audit') loadAudit();
      },
      resyncFn: async () => {
        const d = await adminApi('/api/admin/state');
        sessions = d.sessions || [];
        return d.state;
      },
    });
  }

  async function tryLogin(pin) {
    const errEl = document.getElementById('admin-login-err');
    errEl.classList.add('hidden');
    try {
      await apiJson('/api/admin/login', { method: 'POST', body: JSON.stringify({ pin }) });
      adminPin = pin;
      sessionStorage.setItem('vout_admin_pin', pin);
      loginWrap.classList.add('hidden');
      appWrap.classList.remove('hidden');
      await loadAdminState();
      startSocket();
    } catch (err) {
      sessionStorage.removeItem('vout_admin_pin');
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
      loginWrap.classList.remove('hidden');
      appWrap.classList.add('hidden');
    }
  }

  // ---------------- Quorum Preview ----------------
  function calcReq(qType, total, present) {
    if (qType === 'majority_present') return Math.floor(present / 2) + 1;
    if (qType === 'majority_all') return Math.floor(total / 2) + 1;
    if (qType === 'three_fifths_present') return present > 0 ? Math.floor((3 * present + 4) / 5) : 1;
    if (qType === 'three_fifths_all') return Math.floor((3 * total + 4) / 5);
    return 1;
  }

  function updateQuorumHint() {
    if (!state || !state.attendance) return;
    const sel = document.getElementById('vf-quorum');
    const hint = document.getElementById('vf-quorum-hint');
    const qInfo = (state.quorum_types || {})[sel.value];
    const req = calcReq(sel.value, state.attendance.total_councilors, state.attendance.present_count);
    hint.innerHTML = `Potrebných hlasov ZA pri aktuálnej prezenčke: <strong>${req}</strong>. ${qInfo ? esc(qInfo.legal_hint) : ''}`;
  }

  // ---------------- Renderers ----------------
  function renderAll() {
    if (!state || !state.session) return;
    const { session, attendance } = state;

    document.getElementById('a-session-title').textContent = `${session.title} (č. ${session.session_number})`;
    document.getElementById('a-session-sub').textContent = `${session.body_name} – ${session.municipality_name} • ${session.session_date}`;
    document.getElementById('a-qr-link').href = `/api/admin/sessions/${session.id}/qr-cards`;

    const attBadge = document.getElementById('a-att-badge');
    attBadge.textContent = `Prítomní: ${attendance.present_count} / ${attendance.total_councilors} • ${attendance.quorate ? 'UZNÁŠANIASCHOPNÉ' : 'NEUZNÁŠANIASCHOPNÉ'}`;
    attBadge.className = 'badge ' + (attendance.quorate ? 'badge-green' : 'badge-red');

    // Session selector
    const sel = document.getElementById('a-session-select');
    sel.innerHTML = sessions.map((s) => `<option value="${s.id}" ${s.id === session.id ? 'selected' : ''}>${esc(s.title)} (${esc(s.session_date)})</option>`).join('');

    renderVoteConsole();
    renderAgendaTab();
    renderCouncilorsTab();
    renderHistoryTab();
    renderExportsTab();
  }

  function renderVoteConsole() {
    const { attendance, agenda, current_vote, last_closed_vote } = state;
    const openPanel = document.getElementById('a-open-vote-panel');
    const startForm = document.getElementById('a-start-vote-form');

    // Populate agenda dropdown while preserving current selection
    const agSel = document.getElementById('vf-agenda-select');
    const prevAgVal = agSel.value;
    agSel.innerHTML = `<option value="">— Voľný / procedurálny návrh —</option>` +
      (agenda || []).map((a) => `<option value="${a.id}">Bod ${esc(a.item_number)}: ${esc(a.title.slice(0, 46))}</option>`).join('');
    if (prevAgVal) agSel.value = prevAgVal;

    // Duration chips sync
    document.querySelectorAll('#vf-dur-chips .chip').forEach((c) => {
      c.classList.toggle('active', Number(c.dataset.dur) === Number(selectedDuration));
    });
    updateQuorumHint();

    const btnOpen = document.getElementById('btn-open-vote');
    btnOpen.disabled = !attendance.quorate;
    btnOpen.textContent = attendance.quorate
      ? '▶ Spustiť hlasovanie'
      : `Nedá sa spustiť – neuznášaniaschopné (${attendance.present_count}/${attendance.min_present})`;

    if (current_vote && current_vote.status === 'open') {
      openPanel.classList.remove('hidden');
      startForm.classList.add('hidden');
      const rem = remainingSeconds(current_vote);
      const voted = (current_vote.ballots || []).filter((b) => b.has_voted).length;
      const liveRows = (current_vote.ballots || []).filter((b) => b.was_present).map((b) => `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 0; border-bottom:1px solid #f1f5f9; font-size:0.86rem;">
          <span>${esc(b.short_name)}</span>
          <span class="badge ${b.choice === 'for' ? 'badge-green' : b.choice === 'against' ? 'badge-red' : b.choice === 'abstain' ? 'badge-amber' : 'badge-gray'}">
            ${choiceLabelSk(b.choice)}
          </span>
        </div>
      `).join('');

      openPanel.innerHTML = `
        <div style="background:#eff6ff; border:2px solid #3b82f6; border-radius:10px; padding:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span class="badge badge-blue">OTVORENÉ • Hlasovanie č. ${current_vote.vote_number}</span>
            <strong id="a-open-timer" style="font-size:1.35rem; font-variant-numeric:tabular-nums;">
              ${rem !== null ? `${Math.ceil(rem)} s` : 'Bez limitu'}
            </strong>
          </div>
          <div style="font-weight:800; margin-bottom:4px;">Bod ${esc(current_vote.item_number_snapshot)}: ${esc(current_vote.title)}</div>
          <div class="muted" style="font-size:0.83rem; margin-bottom:10px;">
            ${esc(current_vote.quorum_label)} (potrebných ZA: ${current_vote.required_for}) • Hlasovalo: <strong>${voted}/${current_vote.present_count_snapshot}</strong>
          </div>
          <div style="display:flex; gap:8px;">
            ${current_vote.closes_at ? `<button type="button" id="btn-extend-10" class="btn btn-outline" style="flex:1;">+10 s</button>` : ''}
            <button type="button" id="btn-close-now" class="btn btn-danger" style="flex:2;">■ Uzavrieť teraz</button>
          </div>
          <div style="margin-top:10px; max-height:220px; overflow:auto; background:#fff; border-radius:8px; padding:6px 10px;">
            ${liveRows}
          </div>
        </div>
      `;
      const extBtn = document.getElementById('btn-extend-10');
      if (extBtn) extBtn.addEventListener('click', () => extendVote(current_vote.id, 10));
      document.getElementById('btn-close-now').addEventListener('click', () => closeVote(current_vote.id));
    } else {
      openPanel.classList.add('hidden');
      startForm.classList.remove('hidden');
    }

    // Last closed vote quick actions
    const lastBox = document.getElementById('a-last-vote-box');
    if (last_closed_vote) {
      const v = last_closed_vote;
      const badgeCls = v.passed ? 'badge-green' : 'badge-red';
      lastBox.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; gap:6px;">
          <strong style="font-size:0.9rem;">Posledné hlasovanie č. ${v.vote_number}</strong>
          <span class="badge ${badgeCls}">${esc(v.verdict_sk)}</span>
        </div>
        <div style="font-weight:700; margin:4px 0 6px; font-size:0.92rem;">Bod ${esc(v.item_number_snapshot)}: ${esc(v.title)}</div>
        <div class="muted" style="font-size:0.84rem; margin-bottom:8px;">
          ZA: <strong>${v.for_count}</strong> • PROTI: <strong>${v.against_count}</strong> •
          ZDRŽAL SA: <strong>${v.abstain_count}</strong> • NEHLASOVAL: <strong>${v.not_voted_count}</strong>
          (potrebných ZA: ${v.required_for})
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:6px;">
          ${v.passed && !v.resolution_number
            ? `<button type="button" class="btn btn-primary btn-sm" id="btn-auto-res">Priradiť uznesenie č. ${state.session.next_resolution_seq}/${state.session.resolution_year}</button>`
            : (v.resolution_number ? `<span class="badge badge-blue">Uznesenie č. ${esc(v.resolution_number)}</span>` : '')}
          <button type="button" class="btn btn-outline btn-sm" id="btn-copy-zap">Kopírovať vetu do zápisnice</button>
          <button type="button" class="btn btn-outline btn-sm" id="btn-repeat-last">↻ Opakovať hlasovanie</button>
        </div>
      `;
      const autoRes = document.getElementById('btn-auto-res');
      if (autoRes) {
        autoRes.addEventListener('click', () => assignResolution(v.id, null, true));
      }
      document.getElementById('btn-copy-zap').addEventListener('click', () => copyZapisnicaLine(v.id));
      document.getElementById('btn-repeat-last').addEventListener('click', () => prepareRepeatVote(v));
    } else {
      lastBox.innerHTML = `<div class="muted" style="font-size:0.88rem;">Zatiaľ neprebehlo žiadne hlasovanie.</div>`;
    }
  }

  function renderAgendaTab() {
    const el = document.getElementById('tab-agenda');
    if (el.contains(document.activeElement) && document.activeElement.matches('input, select, textarea')) return;
    const items = state.agenda || [];
    const rows = items.map((a, idx) => `
      <tr class="agenda-row ${a.is_active ? 'active-row' : ''}">
        <td style="white-space:nowrap;"><strong>${esc(a.item_number)}</strong></td>
        <td>
          <div style="font-weight:700;">${esc(a.title)}</div>
          <div class="muted" style="font-size:0.78rem;">${esc((state.quorum_types[a.default_quorum] || {}).short || a.default_quorum)}</div>
        </td>
        <td style="white-space:nowrap; text-align:right;">
          <button class="btn btn-outline btn-sm" data-act="up" data-id="${a.id}" ${idx === 0 ? 'disabled' : ''}>↑</button>
          <button class="btn btn-outline btn-sm" data-act="down" data-id="${a.id}" ${idx === items.length - 1 ? 'disabled' : ''}>↓</button>
          <button class="btn btn-outline btn-sm" data-act="activate" data-id="${a.id}">${a.is_active ? 'Aktívny ✓' : 'Na projektor'}</button>
          <button class="btn btn-primary btn-sm" data-act="prep" data-id="${a.id}">Hlasovať</button>
          <button class="btn btn-outline btn-sm" data-act="amend" data-id="${a.id}" title="Pripraviť pozmeňujúci návrh">+ Pozmeňovák</button>
          <button class="btn btn-outline btn-sm" data-act="del" data-id="${a.id}" style="color:#dc2626;">✕</button>
        </td>
      </tr>
    `).join('');

    el.innerHTML = `
      <form id="add-agenda-form" style="display:grid; grid-template-columns:90px 1fr 190px auto; gap:8px; margin-bottom:14px;">
        <input id="na-num" class="form-control" placeholder="Bod (6.1)" required>
        <input id="na-title" class="form-control" placeholder="Názov nového bodu programu / návrhu…" required>
        <select id="na-quorum" class="form-control">
          <option value="majority_present">&gt;1/2 prítomných</option>
          <option value="majority_all">&gt;1/2 všetkých</option>
          <option value="three_fifths_present">3/5 prítomných (VZN)</option>
          <option value="three_fifths_all">3/5 všetkých</option>
        </select>
        <button type="submit" class="btn btn-primary">+ Pridať bod</button>
      </form>
      <table class="data-table">
        <thead><tr><th>Bod</th><th>Názov a predvolené kvórum</th><th style="text-align:right;">Akcie</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="3" class="muted">Program je zatiaľ prázdny.</td></tr>'}</tbody>
      </table>
    `;

    document.getElementById('add-agenda-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await adminApi(`/api/admin/sessions/${state.session.id}/agenda`, {
          method: 'POST',
          body: JSON.stringify({
            item_number: document.getElementById('na-num').value,
            title: document.getElementById('na-title').value,
            default_quorum: document.getElementById('na-quorum').value,
          }),
        });
        showToast('Bod pridaný do programu.');
      } catch (err) { showToast(err.message, true); }
    });

    el.querySelectorAll('button[data-act]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = Number(btn.dataset.id);
        const act = btn.dataset.act;
        const item = items.find((x) => x.id === id);
        if (!item) return;
        try {
          if (act === 'activate') {
            await adminApi(`/api/admin/sessions/${state.session.id}/agenda/active`, {
              method: 'POST', body: JSON.stringify({ item_id: id }),
            });
          } else if (act === 'prep' || act === 'amend') {
            await adminApi(`/api/admin/sessions/${state.session.id}/agenda/active`, {
              method: 'POST', body: JSON.stringify({ item_id: id }),
            });
            document.getElementById('vf-agenda-select').value = String(id);
            document.getElementById('vf-item-num').value = item.item_number;
            document.getElementById('vf-title').value = act === 'amend' ? `${item.title} – pozmeňujúci návrh` : item.title;
            document.getElementById('vf-quorum').value = item.default_quorum;
            document.getElementById('vf-repeat-from').value = '';
            updateQuorumHint();
            showToast('Pripravené v ovládacom paneli vľavo.');
          } else if (act === 'del') {
            if (!confirm(`Odstrániť bod ${item.item_number}: ${item.title}?`)) return;
            await adminApi(`/api/admin/agenda/${id}`, { method: 'DELETE' });
          } else if (act === 'up' || act === 'down') {
            const idx = items.findIndex((x) => x.id === id);
            const swap = act === 'up' ? idx - 1 : idx + 1;
            const ids = items.map((x) => x.id);
            [ids[idx], ids[swap]] = [ids[swap], ids[idx]];
            await adminApi(`/api/admin/sessions/${state.session.id}/agenda/reorder`, {
              method: 'POST', body: JSON.stringify({ ordered_ids: ids }),
            });
          }
        } catch (err) { showToast(err.message, true); }
      });
    });
  }

  function renderCouncilorsTab() {
    const el = document.getElementById('tab-councilors');
    if (el.contains(document.activeElement) && document.activeElement.matches('input, select, textarea')) return;
    const list = state.councilors || [];
    const rows = list.map((c, idx) => {
      const voteUrl = `${location.origin}/vote?t=${c.token}`;
      return `
        <tr>
          <td>${idx + 1}.</td>
          <td><strong>${esc(c.display_name)}</strong><div class="muted" style="font-size:0.78rem;">${esc(c.district)}</div></td>
          <td><code>${esc(c.pin)}</code></td>
          <td>
            <span class="badge ${c.is_present ? 'badge-green' : (c.excused ? 'badge-amber' : 'badge-gray')}">
              ${c.is_present ? 'V sále (Prítomný)' : (c.excused ? 'Ospravedlnený' : 'Mimo sály')}
            </span>
          </td>
          <td style="text-align:right; white-space:nowrap;">
            <button class="btn ${c.is_present ? 'btn-outline' : 'btn-success'} btn-sm" data-cact="toggle" data-id="${c.id}">
              ${c.is_present ? 'Odhlásiť zo sály' : 'Označiť prítomný'}
            </button>
            ${!c.is_present ? `<button class="btn btn-outline btn-sm" data-cact="excuse" data-id="${c.id}">${c.excused ? 'Zrušiť ospr.' : 'Ospravedlniť'}</button>` : ''}
            <button class="btn btn-outline btn-sm" data-cact="copyurl" data-url="${esc(voteUrl)}">Kopírovať link</button>
            <button class="btn btn-outline btn-sm" data-cact="del" data-id="${c.id}" style="color:#dc2626;">✕</button>
          </td>
        </tr>
      `;
    }).join('');

    el.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <span class="muted" style="font-size:0.88rem;">Zapisovateľ môže manuálne prepnúť prítomnosť (zapisuje sa do audit logu).</span>
        <a href="/api/admin/sessions/${state.session.id}/qr-cards" target="_blank" class="btn btn-primary btn-sm">Vytlačiť QR / PIN karty ↗</a>
      </div>
      <form id="add-councilor-form" style="display:grid; grid-template-columns:80px 1fr 1fr 120px 90px auto; gap:6px; margin-bottom:14px;">
        <input id="nc-title" class="form-control" placeholder="Titul">
        <input id="nc-first" class="form-control" placeholder="Meno" required>
        <input id="nc-last" class="form-control" placeholder="Priezvisko" required>
        <input id="nc-dist" class="form-control" placeholder="Obvod">
        <input id="nc-pin" class="form-control" placeholder="PIN (auto)">
        <button type="submit" class="btn btn-primary">+ Pridať</button>
      </form>
      <table class="data-table">
        <thead><tr><th>#</th><th>Poslanec</th><th>PIN</th><th>Prezenčka</th><th style="text-align:right;">Akcie</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;

    document.getElementById('add-councilor-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await adminApi(`/api/admin/sessions/${state.session.id}/councilors`, {
          method: 'POST',
          body: JSON.stringify({
            title: document.getElementById('nc-title').value,
            first_name: document.getElementById('nc-first').value,
            last_name: document.getElementById('nc-last').value,
            district: document.getElementById('nc-dist').value,
            pin: document.getElementById('nc-pin').value || null,
          }),
        });
        showToast('Poslanec pridaný.');
      } catch (err) { showToast(err.message, true); }
    });

    el.querySelectorAll('button[data-cact]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const act = btn.dataset.cact;
        if (act === 'copyurl') {
          await navigator.clipboard.writeText(btn.dataset.url);
          showToast('Prihlasovací link skopírovaný do schránky.');
          return;
        }
        const id = Number(btn.dataset.id);
        const c = list.find((x) => x.id === id);
        if (!c) return;
        try {
          if (act === 'toggle') {
            await adminApi(`/api/admin/councilors/${id}/presence`, {
              method: 'POST',
              body: JSON.stringify({ is_present: !c.is_present, reason: 'Manuálna zmena prezenčky zapisovateľom' }),
            });
          } else if (act === 'excuse') {
            await adminApi(`/api/admin/councilors/${id}/presence`, {
              method: 'POST',
              body: JSON.stringify({ is_present: false, excused: !c.excused, reason: 'Aktualizácia ospravedlnenia' }),
            });
          } else if (act === 'del') {
            if (!confirm(`Odstrániť poslanca ${c.display_name}?`)) return;
            await adminApi(`/api/admin/councilors/${id}`, { method: 'DELETE' });
          }
        } catch (err) { showToast(err.message, true); }
      });
    });
  }

  function renderHistoryTab() {
    const el = document.getElementById('tab-history');
    if (el.contains(document.activeElement) && document.activeElement.matches('input, select, textarea')) return;
    const votes = [...(state.votes || [])].reverse();
    if (!votes.length) {
      el.innerHTML = '<p class="muted">V tomto zasadnutí zatiaľ nie sú žiadne hlasovania.</p>';
      return;
    }

    el.innerHTML = votes.map((v) => {
      const bCls = v.status === 'open' ? 'badge-blue' : (v.passed ? 'badge-green' : 'badge-red');
      const ballotRows = (v.ballots || []).map((b) => `
        <tr>
          <td>${esc(b.display_name)} ${b.overridden_by_admin ? `<span class="badge badge-amber" title="${esc(b.override_reason)}">Override *</span>` : ''}</td>
          <td><strong>${choiceLabelSk(b.choice)}</strong></td>
          <td style="text-align:right;">
            <button class="btn btn-outline btn-sm" data-ov-vote="${v.id}" data-ov-c="${b.councilor_id}" data-ov-name="${esc(b.display_name)}" data-ov-choice="${esc(b.choice)}">Upraviť (Override)</button>
          </td>
        </tr>
      `).join('');

      return `
        <details style="border:1px solid #cbd5e1; border-radius:10px; padding:10px 12px; margin-bottom:10px;" ${v.id === votes[0].id ? 'open' : ''}>
          <summary style="cursor:pointer; display:flex; justify-content:space-between; align-items:center; gap:8px; font-weight:700;">
            <span>#${v.vote_number} (Bod ${esc(v.item_number_snapshot)}): ${esc(v.title)}</span>
            <span class="badge ${bCls}">${esc(v.verdict_sk || 'OTVORENÉ')} • ZA ${v.for_count}/${v.required_for}</span>
          </summary>
          <div style="margin-top:10px;">
            <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:10px;">
              <span class="muted" style="font-size:0.84rem;">${esc(v.quorum_label)} • Prítomní: ${v.present_count_snapshot}</span>
              <input type="text" class="form-control" style="width:130px; padding:5px 8px;" placeholder="Uznesenie č." value="${esc(v.resolution_number || '')}" data-res-input="${v.id}">
              <button class="btn btn-outline btn-sm" data-res-save="${v.id}">Uložiť č. uznesenia</button>
              <button class="btn btn-outline btn-sm" data-copy-v="${v.id}">Kopírovať vetu</button>
              <button class="btn btn-outline btn-sm" data-rep-v="${v.id}">↻ Opakovať</button>
            </div>
            <table class="data-table">
              <thead><tr><th>Poslanec</th><th>Hlas</th><th style="text-align:right;">Zásah</th></tr></thead>
              <tbody>${ballotRows}</tbody>
            </table>
          </div>
        </details>
      `;
    }).join('');

    el.querySelectorAll('button[data-ov-vote]').forEach((btn) => {
      btn.addEventListener('click', () => {
        openOverrideModal(
          Number(btn.dataset.ovVote),
          Number(btn.dataset.ovC),
          btn.dataset.ovName,
          btn.dataset.ovChoice
        );
      });
    });
    el.querySelectorAll('button[data-res-save]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const vid = Number(btn.dataset.resSave);
        const val = el.querySelector(`input[data-res-input="${vid}"]`).value;
        assignResolution(vid, val, false);
      });
    });
    el.querySelectorAll('button[data-copy-v]').forEach((btn) => {
      btn.addEventListener('click', () => copyZapisnicaLine(Number(btn.dataset.copyV)));
    });
    el.querySelectorAll('button[data-rep-v]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const v = votes.find((x) => x.id === Number(btn.dataset.repV));
        if (v) prepareRepeatVote(v);
      });
    });
  }

  function renderExportsTab() {
    const el = document.getElementById('tab-exports');
    if (el.contains(document.activeElement) && document.activeElement.matches('input, select, textarea')) return;
    const s = state.session;
    el.innerHTML = `
      <h3 style="margin:0 0 8px;">Exporty z tohto zasadnutia</h3>
      <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:18px;">
        <a class="btn btn-primary" href="/api/admin/sessions/${s.id}/export/html" target="_blank">Tlačiteľné Hlasovanie (HTML → PDF) ↗</a>
        <a class="btn btn-outline" href="/api/admin/sessions/${s.id}/export/docx">Stiahnuť Word (.docx)</a>
        <a class="btn btn-outline" href="/api/admin/sessions/${s.id}/export/md">Stiahnuť Markdown (.md)</a>
        <a class="btn btn-outline" href="/api/admin/sessions/${s.id}/export/csv">Stiahnuť Excel CSV (.csv)</a>
        <a class="btn btn-outline" href="/api/admin/sessions/${s.id}/qr-cards" target="_blank">Tlačiť QR/PIN karty ↗</a>
      </div>

      <h3 style="margin:0 0 8px;">Nastavenia aktuálneho zasadnutia</h3>
      <form id="sess-settings-form" style="margin-bottom:20px;">
        <div class="form-row">
          <div class="form-group"><label>Obec / Mestská časť</label><input id="ss-muni" class="form-control" value="${esc(s.municipality_name)}"></div>
          <div class="form-group"><label>Orgán</label><input id="ss-body" class="form-control" value="${esc(s.body_name)}"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Názov zasadnutia</label><input id="ss-title" class="form-control" value="${esc(s.title)}"></div>
          <div class="form-group"><label>Predsedajúci / Starosta</label><input id="ss-chair" class="form-control" value="${esc(s.chair_name)}"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Celkový počet poslancov (kvórum)</label><input id="ss-total" type="number" min="1" class="form-control" value="${s.total_councilors}"></div>
          <div class="form-group"><label>Predvolený odpočet (s)</label><input id="ss-dur" type="number" min="0" class="form-control" value="${s.default_duration_sec}"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Ďalšie číslo uznesenia</label><input id="ss-seq" type="number" min="1" class="form-control" value="${s.next_resolution_seq}"></div>
          <div class="form-group"><label>Rok uznesení</label><input id="ss-year" type="number" min="2020" class="form-control" value="${s.resolution_year}"></div>
        </div>
        <label style="display:flex; align-items:center; gap:8px; margin-bottom:10px; font-size:0.9rem;">
          <input type="checkbox" id="ss-reveal" ${s.reveal_live_votes ? 'checked' : ''}>
          Zobrazovať konkrétne hlasy na projektore už počas odpočtu (predvolene vypnuté – zobrazujú sa len fajočky ✓)
        </label>
        <button type="submit" class="btn btn-primary btn-sm">Uložiť nastavenia zasadnutia</button>
      </form>

      <hr style="border:none; border-top:1px solid #e2e8f0; margin:16px 0;">
      <h3 style="margin:0 0 8px;">Založiť nové zasadnutie</h3>
      <form id="new-session-form">
        <div class="form-row">
          <div class="form-group"><label>Názov nového zasadnutia</label><input id="ns-title" class="form-control" placeholder="napr. 2. zasadnutie MiZ" required></div>
          <div class="form-group"><label>Dátum</label><input id="ns-date" type="date" class="form-control" value="${new Date().toISOString().slice(0, 10)}" required></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Číslo zasadnutia</label><input id="ns-num" class="form-control" value="2"></div>
          <div class="form-group"><label>Počet poslancov</label><input id="ns-total" type="number" min="1" class="form-control" value="${s.total_councilors}"></div>
        </div>
        <button type="submit" class="btn btn-success btn-sm">+ Vytvoriť a aktivovať nové zasadnutie</button>
      </form>
    `;

    document.getElementById('sess-settings-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await adminApi(`/api/admin/sessions/${s.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            municipality_name: document.getElementById('ss-muni').value,
            body_name: document.getElementById('ss-body').value,
            title: document.getElementById('ss-title').value,
            chair_name: document.getElementById('ss-chair').value,
            total_councilors: Number(document.getElementById('ss-total').value),
            default_duration_sec: Number(document.getElementById('ss-dur').value),
            next_resolution_seq: Number(document.getElementById('ss-seq').value),
            resolution_year: Number(document.getElementById('ss-year').value),
            reveal_live_votes: document.getElementById('ss-reveal').checked,
          }),
        });
        showToast('Nastavenia uložené.');
      } catch (err) { showToast(err.message, true); }
    });

    document.getElementById('new-session-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await adminApi('/api/admin/sessions', {
          method: 'POST',
          body: JSON.stringify({
            municipality_name: s.municipality_name,
            body_name: s.body_name,
            title: document.getElementById('ns-title').value,
            session_date: document.getElementById('ns-date').value,
            session_number: document.getElementById('ns-num').value,
            total_councilors: Number(document.getElementById('ns-total').value),
            default_duration_sec: s.default_duration_sec,
          }),
        });
        await loadAdminState();
        showToast('Nové zasadnutie vytvorené a aktivované.');
      } catch (err) { showToast(err.message, true); }
    });
  }

  function renderAuditTab() {
    const el = document.getElementById('tab-audit');
    const rows = auditLogs.map((a) => `
      <tr>
        <td style="white-space:nowrap; font-size:0.8rem;">${esc(a.timestamp.replace('T', ' ').slice(0, 19))}</td>
        <td><span class="badge ${a.actor_type === 'admin' ? 'badge-amber' : a.actor_type === 'system' ? 'badge-blue' : 'badge-gray'}">${esc(a.actor_name)}</span></td>
        <td><code>${esc(a.action)}</code></td>
        <td style="font-size:0.8rem; word-break:break-word;">${esc(JSON.stringify(a.details))}</td>
      </tr>
    `).join('');
    el.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span class="muted" style="font-size:0.85rem;">Nezmazateľný časový záznam všetkých udalostí a manuálnych zásahov (UTC).</span>
        <button class="btn btn-outline btn-sm" id="btn-refresh-audit">Obnoviť</button>
      </div>
      <div style="max-height:540px; overflow:auto;">
        <table class="data-table">
          <thead><tr><th>Čas</th><th>Aktér</th><th>Udalosť</th><th>Detail</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="4" class="muted">Žiadne záznamy.</td></tr>'}</tbody>
        </table>
      </div>
    `;
    document.getElementById('btn-refresh-audit').addEventListener('click', loadAudit);
  }

  // ---------------- Actions ----------------
  async function extendVote(voteId, secs) {
    try {
      await adminApi(`/api/admin/votes/${voteId}/extend`, { method: 'POST', body: JSON.stringify({ add_seconds: secs }) });
      showToast(`Hlasovanie predĺžené o +${secs} s.`);
    } catch (err) { showToast(err.message, true); }
  }

  async function closeVote(voteId) {
    try {
      await adminApi(`/api/admin/votes/${voteId}/close`, { method: 'POST' });
      showToast('Hlasovanie uzavreté.');
    } catch (err) { showToast(err.message, true); }
  }

  async function assignResolution(voteId, num, autoNext) {
    try {
      await adminApi(`/api/admin/votes/${voteId}/resolution`, {
        method: 'POST',
        body: JSON.stringify({ resolution_number: num, auto_next: autoNext }),
      });
      showToast('Číslo uznesenia uložené.');
    } catch (err) { showToast(err.message, true); }
  }

  async function copyZapisnicaLine(voteId) {
    try {
      const d = await adminApi(`/api/admin/votes/${voteId}/zapisnica-line`);
      await navigator.clipboard.writeText(d.text);
      showToast('Veta do zápisnice skopírovaná.');
    } catch (err) { showToast(err.message, true); }
  }

  function prepareRepeatVote(v) {
    document.getElementById('vf-item-num').value = v.item_number_snapshot;
    const baseTitle = v.title.replace(/\s*–\s*opakované hlasovanie$/i, '');
    document.getElementById('vf-title').value = `${baseTitle} – opakované hlasovanie`;
    document.getElementById('vf-quorum').value = v.quorum_type;
    document.getElementById('vf-repeat-from').value = String(v.id);
    updateQuorumHint();
    showToast('Pripravené opakované hlasovanie (pôvodný záznam ostáva zachovaný).');
  }

  function openOverrideModal(voteId, councilorId, name, currentChoice) {
    document.getElementById('ov-vote-id').value = String(voteId);
    document.getElementById('ov-councilor-id').value = String(councilorId);
    document.getElementById('ov-desc').textContent = `Poslanec: ${name} (aktuálne: ${choiceLabelSk(currentChoice)})`;
    document.getElementById('ov-choice').value = currentChoice;
    document.getElementById('ov-reason').value = '';
    document.getElementById('override-modal').classList.remove('hidden');
  }

  // ---------------- Static Event Bindings ----------------
  document.getElementById('admin-login-form').addEventListener('submit', (e) => {
    e.preventDefault();
    tryLogin(document.getElementById('admin-pin-input').value.trim());
  });

  document.getElementById('a-session-select').addEventListener('change', async (e) => {
    const sid = Number(e.target.value);
    try {
      await adminApi(`/api/admin/sessions/${sid}/activate`, { method: 'POST' });
      await loadAdminState(sid);
    } catch (err) { showToast(err.message, true); }
  });

  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      activeTab = btn.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach((b) => b.classList.toggle('active', b === btn));
      document.querySelectorAll('.tab-panel').forEach((p) => p.classList.toggle('hidden', p.id !== `tab-${activeTab}`));
      if (activeTab === 'audit') loadAudit();
    });
  });

  document.getElementById('vf-quorum').addEventListener('change', updateQuorumHint);
  document.getElementById('vf-agenda-select').addEventListener('change', (e) => {
    const id = Number(e.target.value);
    const item = (state.agenda || []).find((a) => a.id === id);
    if (item) {
      document.getElementById('vf-item-num').value = item.item_number;
      document.getElementById('vf-title').value = item.title;
      document.getElementById('vf-quorum').value = item.default_quorum;
      updateQuorumHint();
    }
  });

  document.querySelectorAll('#vf-dur-chips .chip').forEach((c) => {
    c.addEventListener('click', () => {
      selectedDuration = Number(c.dataset.dur);
      document.querySelectorAll('#vf-dur-chips .chip').forEach((x) => x.classList.toggle('active', x === c));
    });
  });

  document.getElementById('a-start-vote-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const agId = document.getElementById('vf-agenda-select').value;
    const repId = document.getElementById('vf-repeat-from').value;
    try {
      await adminApi(`/api/admin/sessions/${state.session.id}/votes/open`, {
        method: 'POST',
        body: JSON.stringify({
          title: document.getElementById('vf-title').value,
          item_number_snapshot: document.getElementById('vf-item-num').value,
          quorum_type: document.getElementById('vf-quorum').value,
          duration_sec: selectedDuration,
          agenda_item_id: agId ? Number(agId) : null,
          repeated_from_vote_id: repId ? Number(repId) : null,
        }),
      });
      document.getElementById('vf-repeat-from').value = '';
      showToast('Hlasovanie spustené!');
    } catch (err) { showToast(err.message, true); }
  });

  document.getElementById('ov-cancel').addEventListener('click', () => {
    document.getElementById('override-modal').classList.add('hidden');
  });

  document.getElementById('override-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const voteId = Number(document.getElementById('ov-vote-id').value);
    const councilorId = Number(document.getElementById('ov-councilor-id').value);
    const choice = document.getElementById('ov-choice').value;
    const reason = document.getElementById('ov-reason').value.trim();
    try {
      await adminApi(`/api/admin/votes/${voteId}/override`, {
        method: 'POST',
        body: JSON.stringify({ councilor_id: councilorId, choice, reason }),
      });
      document.getElementById('override-modal').classList.add('hidden');
      showToast('Manuálny zásah uložený a výsledok prepočítaný.');
    } catch (err) { showToast(err.message, true); }
  });

  // Live countdown ticker in admin console
  setInterval(() => {
    if (!state || !state.current_vote || state.current_vote.status !== 'open') return;
    const el = document.getElementById('a-open-timer');
    if (!el) return;
    const rem = remainingSeconds(state.current_vote);
    if (rem !== null) el.textContent = `${Math.ceil(rem)} s`;
  }, 150);

  if (adminPin) {
    tryLogin(adminPin);
  }
})();
