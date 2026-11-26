/* /display — Projector / TV live board */

(() => {
  const { esc, apiJson, choiceLabelSk, remainingSeconds, createResilientSocket } = window.VoutCommon;

  let state = null;

  function render() {
    if (!state || !state.session) {
      document.getElementById('d-org').textContent = 'vout';
      document.getElementById('d-session').textContent = 'Žiadne aktívne zasadnutie';
      return;
    }

    const { session, attendance, councilors, active_agenda_item, current_vote, last_closed_vote } = state;

    document.getElementById('d-org').textContent = `${session.body_name} – ${session.municipality_name}`;
    document.getElementById('d-session').textContent = `${session.title} (${session.session_date})`;
    document.getElementById('d-att-num').textContent = `${attendance.present_count} / ${attendance.total_councilors}`;

    const qPill = document.getElementById('d-quorum-pill');
    if (attendance.quorate) {
      qPill.textContent = 'UZNÁŠANIASCHOPNÉ';
      qPill.className = 'disp-quorum-pill ok';
    } else {
      qPill.textContent = `NEUZNÁŠANIASCHOPNÉ (min. ${attendance.min_present})`;
      qPill.className = 'disp-quorum-pill bad';
    }

    const stage = document.getElementById('d-stage');
    const grid = document.getElementById('d-grid');

    if (current_vote && current_vote.status === 'open') {
      // STATE 1: OPEN VOTE (countdown + checkmarks only unless reveal_live_votes)
      stage.className = 'disp-stage stage-open';
      const rem = remainingSeconds(current_vote);
      const timerHtml = rem !== null
        ? `<div class="disp-countdown">
             <div id="d-countdown-val" class="disp-countdown-val">${Math.ceil(rem)}s</div>
             <div class="disp-countdown-lbl">ODPOČET</div>
           </div>`
        : `<div class="disp-countdown">
             <div class="disp-countdown-val" style="font-size:2.2rem;">OTVORENÉ</div>
             <div class="disp-countdown-lbl">HLASUJE SA</div>
           </div>`;

      const voted = current_vote.voted_count ?? 0;
      const present = current_vote.present_count_snapshot ?? attendance.present_count;

      stage.innerHTML = `
        <div class="disp-stage-top">
          <div style="flex:1;">
            <div class="disp-vote-meta">Hlasovanie č. ${current_vote.vote_number} • Bod ${esc(current_vote.item_number_snapshot)}</div>
            <div class="disp-vote-title">${esc(current_vote.title)}</div>
            <div class="disp-quorum-info">
              Kvórum: <strong>${esc(current_vote.quorum_label)}</strong> (potrebných ZA: <strong>${current_vote.required_for}</strong>)
              &nbsp;•&nbsp; Odovzdané hlasy: <strong>${voted} / ${present}</strong>
            </div>
            ${rem !== null ? '<div class="progress-track" style="height:10px; margin-top:14px;"><div id="d-timer-bar" class="progress-fill" style="width:100%;"></div></div>' : ''}
          </div>
          ${timerHtml}
        </div>
      `;

      grid.innerHTML = (current_vote.ballots || []).map((b) => {
        if (!b.was_present) {
          return `<div class="disp-person is-absent">
            <div><div class="disp-person-name">${esc(b.short_name)}</div><div class="disp-person-sub">${esc(b.district)}</div></div>
            <span class="disp-person-badge dp-absent">MIMO SÁLY</span>
          </div>`;
        }
        if (b.choice) {
          // Only happens if reveal_live_votes is explicitly ON
          return `<div class="disp-person res-${esc(b.choice)}">
            <div><div class="disp-person-name">${esc(b.short_name)}</div><div class="disp-person-sub">${esc(b.district)}</div></div>
            <span class="disp-person-badge dp-${esc(b.choice)}">${choiceLabelSk(b.choice)}</span>
          </div>`;
        }
        if (b.has_voted) {
          return `<div class="disp-person voted-check">
            <div><div class="disp-person-name">${esc(b.short_name)}</div><div class="disp-person-sub">${esc(b.district)}</div></div>
            <span class="disp-person-badge dp-check">✓ HLASOVAL</span>
          </div>`;
        }
        return `<div class="disp-person">
          <div><div class="disp-person-name">${esc(b.short_name)}</div><div class="disp-person-sub">${esc(b.district)}</div></div>
          <span class="disp-person-badge dp-wait">Čaká sa…</span>
        </div>`;
      }).join('');

      updateCountdown();
    } else if (last_closed_vote) {
      // STATE 2: CLOSED VOTE RESULT (full roll-call + big verdict)
      const v = last_closed_vote;
      stage.className = 'disp-stage ' + (v.passed ? 'stage-passed' : 'stage-failed');
      const resBadge = v.resolution_number ? ` • Uznesenie č. ${esc(v.resolution_number)}` : '';
      const activeBanner = active_agenda_item
        ? `<div style="margin-top:8px; font-size:0.95rem; color:#94a3b8;">Aktuálny bod programu: <strong style="color:#e2e8f0;">Bod ${esc(active_agenda_item.item_number)} – ${esc(active_agenda_item.title)}</strong></div>`
        : '';

      stage.innerHTML = `
        <div class="disp-stage-top">
          <div style="flex:1;">
            <div class="disp-vote-meta">Výsledok hlasovania č. ${v.vote_number} • Bod ${esc(v.item_number_snapshot)}${resBadge}</div>
            <div class="disp-vote-title">${esc(v.title)}</div>
            <div class="disp-quorum-info">
              Kvórum: <strong>${esc(v.quorum_label)}</strong> • Potrebných ZA: <strong>${v.required_for}</strong>
            </div>
            ${activeBanner}
          </div>
          <div class="disp-verdict-box">
            <div class="disp-verdict-word ${v.passed ? 'passed' : 'failed'}">${esc(v.verdict_sk)}</div>
          </div>
        </div>
        <div class="disp-counters">
          <div class="disp-counter c-for"><div class="c-num">${v.for_count}</div><div class="c-lbl">ZA</div></div>
          <div class="disp-counter c-against"><div class="c-num">${v.against_count}</div><div class="c-lbl">PROTI</div></div>
          <div class="disp-counter c-abstain"><div class="c-num">${v.abstain_count}</div><div class="c-lbl">ZDRŽAL SA</div></div>
          <div class="disp-counter c-notvoted"><div class="c-num">${v.not_voted_count}</div><div class="c-lbl">NEHLASOVAL</div></div>
          <div class="disp-counter c-present"><div class="c-num">${v.present_count_snapshot}</div><div class="c-lbl">PRÍTOMNÍ</div></div>
        </div>
      `;

      grid.innerHTML = (v.ballots || []).map((b) => {
        if (b.choice === 'absent') {
          return `<div class="disp-person is-absent">
            <div><div class="disp-person-name">${esc(b.short_name)}</div><div class="disp-person-sub">${esc(b.district)}</div></div>
            <span class="disp-person-badge dp-absent">NEPRÍTOMNÝ</span>
          </div>`;
        }
        const star = b.overridden_by_admin ? ' *' : '';
        return `<div class="disp-person res-${esc(b.choice)}">
          <div><div class="disp-person-name">${esc(b.short_name)}${star}</div><div class="disp-person-sub">${esc(b.district)}</div></div>
          <span class="disp-person-badge dp-${esc(b.choice)}">${choiceLabelSk(b.choice)}</span>
        </div>`;
      }).join('');
    } else {
      // STATE 3: IDLE / PRE-VOTE ATTENDANCE BOARD
      stage.className = 'disp-stage';
      const itemTitle = active_agenda_item
        ? `Bod ${esc(active_agenda_item.item_number)}: ${esc(active_agenda_item.title)}`
        : 'Pripravené na začatie rokovania';
      stage.innerHTML = `
        <div class="disp-vote-meta">Aktuálny bod programu</div>
        <div class="disp-vote-title">${itemTitle}</div>
        <div class="disp-quorum-info">Čaká sa na spustenie hlasovania…</div>
      `;

      grid.innerHTML = (councilors || []).map((c) => {
        const cls = c.is_present ? '' : 'is-absent';
        const bCls = c.is_present ? 'dp-present' : 'dp-absent';
        const bTxt = c.is_present ? 'PRÍTOMNÝ' : 'MIMO SÁLY';
        return `<div class="disp-person ${cls}">
          <div><div class="disp-person-name">${esc(c.short_name)}</div><div class="disp-person-sub">${esc(c.district)}</div></div>
          <span class="disp-person-badge ${bCls}">${bTxt}</span>
        </div>`;
      }).join('');
    }
  }

  function updateCountdown() {
    if (!state || !state.current_vote || state.current_vote.status !== 'open') return;
    const rem = remainingSeconds(state.current_vote);
    const valEl = document.getElementById('d-countdown-val');
    const barEl = document.getElementById('d-timer-bar');
    if (rem === null || !valEl) return;
    const sec = Math.ceil(rem);
    valEl.textContent = `${sec}s`;
    valEl.className = 'disp-countdown-val' + (sec <= 3 ? ' danger' : sec <= 5 ? ' warn' : '');
    if (barEl && state.current_vote.duration_sec > 0) {
      const pct = Math.max(0, Math.min(100, (rem / state.current_vote.duration_sec) * 100));
      barEl.style.width = `${pct}%`;
    }
  }

  createResilientSocket({
    wsPath: '/ws/display',
    onState(newState) {
      state = newState;
      render();
    },
    resyncFn: () => apiJson('/api/display/state'),
  });

  setInterval(updateCountdown, 150);
})();
