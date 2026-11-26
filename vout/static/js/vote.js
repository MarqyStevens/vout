/* /vote — Mobile-first councilor voting & virtual presence card ("kartička") */

(() => {
  const { esc, apiJson, showToast, choiceLabelSk, remainingSeconds, createResilientSocket } = window.VoutCommon;

  let voterToken = null;
  let state = null;
  let socket = null;
  let tickTimer = null;

  const loginView = document.getElementById('login-view');
  const voterView = document.getElementById('voter-view');
  const pinForm = document.getElementById('pin-form');
  const pinInput = document.getElementById('pin-input');
  const loginError = document.getElementById('login-error');
  const connDot = document.getElementById('v-conn-dot');

  async function doAuth(payload) {
    loginError.classList.add('hidden');
    try {
      const res = await apiJson('/api/vote/auth', { method: 'POST', body: JSON.stringify(payload) });
      voterToken = res.token;
      localStorage.setItem('vout_voter_token', voterToken);
      if (location.search) {
        history.replaceState({}, '', '/vote');
      }
      state = res.state;
      showVoterScreen();
      startRealtime();
      render();
    } catch (err) {
      localStorage.removeItem('vout_voter_token');
      loginError.textContent = err.message || 'Prihlásenie zlyhalo.';
      loginError.classList.remove('hidden');
      showLoginScreen();
    }
  }

  function showLoginScreen() {
    loginView.classList.remove('hidden');
    voterView.classList.add('hidden');
  }

  function showVoterScreen() {
    loginView.classList.add('hidden');
    voterView.classList.remove('hidden');
  }

  function startRealtime() {
    if (socket) socket.close();
    socket = createResilientSocket({
      wsPath: `/ws/vote/${encodeURIComponent(voterToken)}`,
      onStatus(ok) {
        connDot.className = 'conn-dot ' + (ok ? 'ok' : 'err');
      },
      onState(newState) {
        state = newState;
        render();
      },
      resyncFn: () => apiJson(`/api/vote/state?token=${encodeURIComponent(voterToken)}`),
    });
    clearInterval(tickTimer);
    tickTimer = setInterval(updateCountdownOnly, 150);
  }

  function updateCountdownOnly() {
    if (!state || !state.current_vote || state.current_vote.status !== 'open') return;
    const rem = remainingSeconds(state.current_vote);
    const numEl = document.getElementById('v-timer-num');
    const barEl = document.getElementById('v-timer-bar');
    if (rem === null || !numEl) return;
    const sec = Math.ceil(rem);
    numEl.textContent = `${sec} s`;
    numEl.className = 'vote-timer-num' + (sec <= 3 ? ' danger' : sec <= 5 ? ' warn' : '');
    if (barEl && state.current_vote.duration_sec > 0) {
      const pct = Math.max(0, Math.min(100, (rem / state.current_vote.duration_sec) * 100));
      barEl.style.width = `${pct}%`;
    }
  }

  function render() {
    if (!state || !state.session || !state.me) return;
    const { session, attendance, me, current_vote, my_ballot, last_closed_vote, active_agenda_item } = state;

    document.getElementById('v-org').textContent = `${session.body_name} • ${session.municipality_name}`;
    document.getElementById('v-name').textContent = me.display_name;
    document.getElementById('v-session').textContent = `${session.title} (${session.session_date})`;

    // Virtual card ("kartička")
    const pCard = document.getElementById('card-presence');
    const pLabel = document.getElementById('v-presence-label');
    const pBtn = document.getElementById('btn-toggle-presence');
    const pHint = document.getElementById('v-presence-hint');
    const qBadge = document.getElementById('v-quorum-badge');

    qBadge.textContent = `Prítomní: ${attendance.present_count} / ${attendance.total_councilors}`;
    qBadge.className = 'badge ' + (attendance.quorate ? 'badge-green' : 'badge-red');

    const voteOpen = Boolean(current_vote && current_vote.status === 'open');
    if (me.is_present) {
      pCard.className = 'card card-presence in-hall';
      pLabel.textContent = 'V SÁLE – PRÍTOMNÝ';
      pLabel.style.color = '#166534';
      pBtn.textContent = 'Vytiahnuť kartičku – Odchod zo sály';
      pBtn.className = 'btn btn-outline presence-btn';
    } else {
      pCard.className = 'card card-presence out-hall';
      pLabel.textContent = 'MIMO SÁLY (NEPRÍTOMNÝ)';
      pLabel.style.color = '#92400e';
      pBtn.textContent = 'Zasunúť kartičku – Som v sále';
      pBtn.className = 'btn btn-success presence-btn';
    }
    pBtn.disabled = voteOpen;
    pHint.textContent = voteOpen
      ? 'Počas bežiaceho odpočtu hlasovania je kartička zamknutá.'
      : 'Pri odchode zo sály kartičku vytiahnite, aby ste nezvyšovali kvórum.';

    // Active Voting Area
    const area = document.getElementById('v-vote-area');
    if (voteOpen) {
      const rem = remainingSeconds(current_vote);
      const timerHtml = rem !== null
        ? `<div class="vote-timer-box">
             <div style="font-size:0.8rem; text-transform:uppercase; color:#94a3b8; font-weight:700;">Zostávajúci čas na hlasovanie</div>
             <div id="v-timer-num" class="vote-timer-num">${Math.ceil(rem)} s</div>
             <div class="progress-track"><div id="v-timer-bar" class="progress-fill" style="width:100%"></div></div>
           </div>`
        : `<div class="vote-timer-box">
             <div style="font-size:1rem; font-weight:800; color:#38bdf8;">HLASOVANIE OTVORENÉ</div>
             <div style="font-size:0.85rem; color:#94a3b8;">Čaká sa na uzavretie predsedajúcim</div>
           </div>`;

      const canVote = Boolean(my_ballot && my_ballot.was_present);
      const myChoice = my_ballot ? my_ballot.choice : null;

      let buttonsHtml = '';
      if (!canVote) {
        buttonsHtml = `<div class="badge badge-amber" style="width:100%; justify-content:center; padding:12px; border-radius:10px; margin-top:12px;">
          Pri spustení hlasovania ste boli mimo sály (vytiahnutá kartička).
        </div>`;
      } else {
        const mkBtn = (val, label, cls) => {
          const isSel = myChoice === val;
          const isDim = myChoice && myChoice !== 'not_voted' && !isSel;
          return `<button class="vbtn ${cls}${isSel ? ' selected' : ''}${isDim ? ' dimmed' : ''}" data-choice="${val}">
            <span>${label}</span>
            <span>${isSel ? '✓ VÁŠ HLAS' : ''}</span>
          </button>`;
        };
        buttonsHtml = `
          <div class="vote-buttons">
            ${mkBtn('for', 'ZA', 'for')}
            ${mkBtn('against', 'PROTI', 'against')}
            ${mkBtn('abstain', 'ZDRŽAL SA', 'abstain')}
          </div>
          <p class="muted" style="text-align:center; font-size:0.84rem; margin:10px 0 0;">
            ${myChoice && myChoice !== 'not_voted'
              ? `Zaznamenaný hlas: <strong>${choiceLabelSk(myChoice)}</strong>. Do konca odpočtu ho môžete zmeniť.`
              : 'Ťuknite na svoju voľbu. Kto nehlasuje do konca odpočtu, bude vedený ako NEHLASOVAL.'}
          </p>
        `;
      }

      area.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:6px;">
          <span class="badge badge-blue">Hlasovanie č. ${current_vote.vote_number} • Bod ${esc(current_vote.item_number_snapshot)}</span>
          <span class="badge badge-gray">${esc(current_vote.quorum_short)}</span>
        </div>
        <h2 style="margin:4px 0 12px; font-size:1.2rem; line-height:1.3;">${esc(current_vote.title)}</h2>
        ${timerHtml}
        ${buttonsHtml}
      `;
      updateCountdownOnly();
      area.querySelectorAll('.vbtn').forEach((btn) => {
        btn.addEventListener('click', () => castVote(current_vote.id, btn.dataset.choice));
      });
    } else {
      const agendaTxt = active_agenda_item
        ? `Bod ${esc(active_agenda_item.item_number)}: ${esc(active_agenda_item.title)}`
        : 'Žiadny aktívny bod programu';
      area.innerHTML = `
        <div style="text-align:center; padding:12px 4px;">
          <div class="badge badge-gray" style="margin-bottom:8px;">Aktuálny bod programu</div>
          <div style="font-weight:800; font-size:1.05rem; margin-bottom:6px;">${agendaTxt}</div>
          <div class="muted" style="font-size:0.9rem;">Čaká sa na spustenie hlasovania zapisovateľom…</div>
        </div>
      `;
    }

    // Last closed vote summary
    const lastBox = document.getElementById('v-last-result');
    if (last_closed_vote) {
      const myPrev = (last_closed_vote.ballots || []).find((b) => b.councilor_id === me.id);
      const passedCls = last_closed_vote.passed ? 'badge-green' : 'badge-red';
      lastBox.classList.remove('hidden');
      lastBox.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:6px;">
          <span class="muted" style="font-size:0.82rem; font-weight:700;">Posledné hlasovanie č. ${last_closed_vote.vote_number}</span>
          <span class="badge ${passedCls}">${esc(last_closed_vote.verdict_sk)}</span>
        </div>
        <div style="font-weight:800; margin-bottom:8px;">${esc(last_closed_vote.title)}</div>
        <div style="display:flex; flex-wrap:wrap; gap:8px; font-size:0.86rem; margin-bottom:8px;">
          <span><strong>ZA:</strong> ${last_closed_vote.for_count}</span>
          <span><strong>PROTI:</strong> ${last_closed_vote.against_count}</span>
          <span><strong>ZDRŽAL SA:</strong> ${last_closed_vote.abstain_count}</span>
          <span><strong>NEHLASOVAL:</strong> ${last_closed_vote.not_voted_count}</span>
          <span><strong>Potrebných:</strong> ${last_closed_vote.required_for}</span>
        </div>
        ${myPrev ? `<div class="muted" style="font-size:0.84rem;">Váš hlas: <strong>${choiceLabelSk(myPrev.choice)}</strong></div>` : ''}
      `;
    } else {
      lastBox.classList.add('hidden');
    }
  }

  async function togglePresence() {
    if (!state || !state.me) return;
    try {
      state = await apiJson('/api/vote/presence', {
        method: 'POST',
        body: JSON.stringify({ token: voterToken, is_present: !state.me.is_present }),
      });
      render();
      showToast(state.me.is_present ? 'Kartička zasunutá – ste v sále.' : 'Kartička vytiahnutá – mimo sály.');
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function castVote(voteId, choice) {
    try {
      state = await apiJson('/api/vote/cast', {
        method: 'POST',
        body: JSON.stringify({ token: voterToken, vote_id: voteId, choice }),
      });
      render();
      showToast(`Hlas zaznamenaný: ${choiceLabelSk(choice)}`);
    } catch (err) {
      showToast(err.message, true);
    }
  }

  // Event bindings
  pinForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const pin = pinInput.value.trim();
    if (pin) doAuth({ pin });
  });

  document.getElementById('btn-toggle-presence').addEventListener('click', togglePresence);
  document.getElementById('btn-logout').addEventListener('click', () => {
    localStorage.removeItem('vout_voter_token');
    voterToken = null;
    if (socket) socket.close();
    pinInput.value = '';
    showLoginScreen();
  });

  // Boot: QR token in URL > saved localStorage token > PIN screen
  const urlToken = new URLSearchParams(location.search).get('t');
  const savedToken = localStorage.getItem('vout_voter_token');
  if (urlToken) {
    doAuth({ token: urlToken });
  } else if (savedToken) {
    doAuth({ token: savedToken });
  } else {
    showLoginScreen();
  }
})();
