"""Export generators for print-ready HTML/PDF (MČ Furča format), DOCX, Markdown, CSV, and QR cards."""

from __future__ import annotations

import csv
import html
import io
from typing import Any

import segno
from docx import Document
from docx.shared import Pt, RGBColor

from .db import Database
from .quorum import QUORUM_LABELS

CHOICE_LABELS_SK = {
    "for": "ZA",
    "against": "PROTI",
    "abstain": "ZDRŽAL SA",
    "not_voted": "NEHLASOVAL",
    "absent": "NEPRÍTOMNÝ",
}


def format_zapisnica_sentence(vote: dict[str, Any]) -> str:
    """Generate the exact 1-line voting summary sentence used in MČ Furča minutes."""
    if not vote.get("quorum_met", True):
        verdict_phrase = "zastupiteľstvo nebolo uznášaniaschopné."
    elif vote.get("passed"):
        verdict_phrase = "uznesenie bolo schválené."
    else:
        verdict_phrase = "návrh nebol schválený."

    parts = [
        f"za {vote['for_count']}",
        f"proti {vote['against_count']}",
        f"zdržal sa {vote['abstain_count']}",
    ]
    if vote.get("not_voted_count", 0) > 0:
        parts.append(f"nehlasoval {vote['not_voted_count']}")
    return f"Hlasovanie: {', '.join(parts)}, {verdict_phrase}"


def _names_by_choice(vote: dict[str, Any], choice: str) -> list[str]:
    names = []
    for b in vote.get("ballots", []):
        if b["choice"] == choice:
            label = b["short_name"]
            if b.get("overridden_by_admin"):
                label += " *"
            names.append(label)
    return names


def render_hlasovanie_html(db: Database, session_id: int) -> str:
    """Render print-ready HTML matching MČ Furča's official 'Hlasovanie' PDF structure."""
    sess = db.get_session(session_id)
    if not sess:
        raise KeyError("Zasadnutie neexistuje.")
    councilors = db.list_councilors(session_id)
    votes = db.list_votes(session_id, include_ballots=True)
    esc = html.escape

    # Page 1: Prezenčná listina
    attendance_rows = []
    for idx, c in enumerate(councilors, start=1):
        if c["ever_present"] or c["is_present"]:
            status_txt = "zúčastnil/a sa"
        elif c["excused"]:
            status_txt = "nezúčastnil/a sa (ospravedlnený/á)"
        else:
            status_txt = "nezúčastnil/a sa"
        attendance_rows.append(
            f"<tr><td class='num'>{idx}.</td><td>{esc(c['display_name'])}</td>"
            f"<td>{esc(c['district'])}</td><td><strong>{esc(status_txt)}</strong></td></tr>"
        )

    # Page 2+: HLASOVANIE POSLANCOV
    vote_blocks = []
    for v in votes:
        q_label = QUORUM_LABELS[v["quorum_type"]]["label"]
        verdict = v["verdict_sk"] or ("OTVORENÉ" if v["status"] == "open" else "UZAVRETÉ")
        verdict_cls = "passed" if v["passed"] else "failed"
        res_line = f"č. {esc(v['resolution_number'])}" if v.get("resolution_number") else "—"

        name_lines = []
        for key, heading in [
            ("for", "Za"),
            ("against", "Proti"),
            ("abstain", "Zdržali sa"),
            ("not_voted", "Nehlasovali"),
        ]:
            names = _names_by_choice(v, key)
            if names:
                name_lines.append(
                    f"<div class='names-row'><strong>{heading}:</strong> {esc(', '.join(names))}</div>"
                )

        overrides = [
            f"{b['short_name']} ({CHOICE_LABELS_SK.get(b['choice'], b['choice'])} – dôvod: {b['override_reason']})"
            for b in v.get("ballots", [])
            if b.get("overridden_by_admin")
        ]
        override_html = ""
        if overrides:
            override_html = (
                "<div class='override-note'><em>* Manuálny zásah zapisovateľa (audit log): "
                + esc("; ".join(overrides))
                + "</em></div>"
            )

        vote_blocks.append(
            f"""
            <article class="vote-block">
              <div class="vote-head">
                <div>
                  <div class="meta-line"><strong>Číslo hlasovania :</strong> {v['vote_number']} &nbsp;|&nbsp;
                  <strong>Číslo bodu :</strong> {esc(v['item_number_snapshot'])}</div>
                  <h3>{esc(v['title'])}</h3>
                  <div class="meta-line"><strong>Uznesenie:</strong> {res_line} &nbsp;|&nbsp;
                  <strong>Kvórum:</strong> {esc(q_label)} (potrebných ZA: {v['required_for']})</div>
                </div>
                <div class="verdict {verdict_cls}">{esc(verdict)}</div>
              </div>
              <div class="counts-bar">
                <span><strong>Za:</strong> {v['for_count']}</span>
                <span><strong>Proti:</strong> {v['against_count']}</span>
                <span><strong>Zdržali sa:</strong> {v['abstain_count']}</span>
                <span><strong>Nehlasovali:</strong> {v['not_voted_count']}</span>
                <span><strong>Prítomní:</strong> {v['present_count_snapshot']} / {v['total_councilors_snapshot']}</span>
              </div>
              <div class="names-list">
                {''.join(name_lines) or '<div class="names-row"><em>Žiadne odovzdané hlasy.</em></div>'}
              </div>
              {override_html}
              <div class="zapisnica-line">{esc(format_zapisnica_sentence(v))}</div>
            </article>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="sk">
<head>
<meta charset="utf-8">
<title>Hlasovanie – {esc(sess['title'])} ({esc(sess['session_date'])})</title>
<style>
  @page {{ size: A4; margin: 16mm; }}
  body {{ font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; color: #111; line-height: 1.45; margin: 0; padding: 24px; max-width: 900px; margin-inline: auto; }}
  .no-print {{ display: flex; gap: 12px; margin-bottom: 20px; padding: 12px; background: #f1f5f9; border-radius: 8px; align-items: center; justify-content: space-between; }}
  .no-print button {{ padding: 10px 18px; font-weight: 700; cursor: pointer; background: #0f172a; color: #fff; border: 0; border-radius: 6px; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px 0; }}
  h2 {{ font-size: 1.15rem; border-bottom: 2px solid #111; padding-bottom: 4px; margin-top: 24px; }}
  h3 {{ font-size: 1.05rem; margin: 6px 0; }}
  .sub {{ color: #475569; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
  th, td {{ border-bottom: 1px solid #cbd5e1; padding: 7px 8px; text-align: left; font-size: 0.94rem; }}
  td.num {{ width: 36px; color: #64748b; }}
  .page-break {{ page-break-before: always; break-before: page; }}
  .vote-block {{ border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px 14px; margin-bottom: 14px; page-break-inside: avoid; break-inside: avoid; }}
  .vote-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
  .meta-line {{ font-size: 0.88rem; color: #334155; }}
  .verdict {{ font-weight: 800; font-size: 0.9rem; padding: 5px 10px; border-radius: 6px; white-space: nowrap; }}
  .verdict.passed {{ background: #dcfce7; color: #166534; border: 1px solid #86efac; }}
  .verdict.failed {{ background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }}
  .counts-bar {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 8px 0; padding: 6px 10px; background: #f8fafc; border-radius: 6px; font-size: 0.9rem; }}
  .names-row {{ font-size: 0.9rem; margin: 4px 0; }}
  .override-note {{ font-size: 0.82rem; color: #92400e; background: #fef3c7; padding: 6px 8px; border-radius: 4px; margin-top: 6px; }}
  .zapisnica-line {{ font-size: 0.86rem; color: #334155; border-top: 1px dashed #cbd5e1; margin-top: 8px; padding-top: 6px; }}
  .signatures {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; margin-top: 40px; page-break-inside: avoid; }}
  .sig-box {{ border-top: 1px solid #334155; padding-top: 6px; text-align: center; font-size: 0.88rem; color: #334155; }}
  @media print {{
    body {{ padding: 0; max-width: none; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
  <div class="no-print">
    <span><strong>Tlačiteľný výpis hlasovaní</strong> (Uložiť ako PDF cez Tlačiť → Uložiť ako PDF)</span>
    <button onclick="window.print()">Tlačiť / Uložiť PDF</button>
  </div>

  <header>
    <h1>{esc(sess['body_name'])} – {esc(sess['municipality_name'])}</h1>
    <div class="sub">
      <strong>{esc(sess['title'])}</strong> (č. {esc(sess['session_number'])}) &nbsp;|&nbsp;
      Dátum: <strong>{esc(sess['session_date'])}</strong>
      {f" &nbsp;|&nbsp; Rokovanie viedol: {esc(sess['chair_name'])}" if sess.get('chair_name') else ""}
    </div>
  </header>

  <h2>Prezenčná listina</h2>
  <table>
    <thead><tr><th>#</th><th>Priezvisko a meno</th><th>Obvod / poznámka</th><th>Účasť</th></tr></thead>
    <tbody>{''.join(attendance_rows)}</tbody>
  </table>

  <div class="page-break"></div>
  <h2>HLASOVANIE POSLANCOV</h2>
  {''.join(vote_blocks) or '<p><em>V tomto zasadnutí zatiaľ neprebehli žiadne hlasovania.</em></p>'}

  <div class="signatures">
    <div class="sig-box">Starosta / Predsedajúci</div>
    <div class="sig-box">Overovateľ zápisnice č. 1</div>
    <div class="sig-box">Overovateľ zápisnice č. 2</div>
  </div>
</body>
</html>"""


def render_qr_cards_html(db: Database, session_id: int, base_url: str) -> str:
    """Generate printable A4 access cards with inline SVG QR codes + PIN for each councilor."""
    sess = db.get_session(session_id)
    if not sess:
        raise KeyError("Zasadnutie neexistuje.")
    councilors = db.list_councilors(session_id)
    esc = html.escape
    base = base_url.rstrip("/")

    cards = []
    for c in councilors:
        vote_url = f"{base}/vote?t={c['token']}"
        qr = segno.make(vote_url, error="M")
        buf = io.BytesIO()
        qr.save(buf, kind="svg", scale=4, border=2, xmldecl=False)
        svg_str = buf.getvalue().decode("utf-8")
        cards.append(
            f"""
            <div class="card">
              <div class="card-header">{esc(sess['municipality_name'])}</div>
              <div class="card-session">{esc(sess['title'])} ({esc(sess['session_date'])})</div>
              <div class="card-name">{esc(c['display_name'])}</div>
              <div class="qr-wrap">{svg_str}</div>
              <div class="card-pin">PIN: <strong>{esc(c['pin'])}</strong></div>
              <div class="card-url">{esc(base)}/vote</div>
            </div>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="sk">
<head>
<meta charset="utf-8">
<title>Prístupové QR karty – {esc(sess['title'])}</title>
<style>
  @page {{ size: A4; margin: 10mm; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 16px; color: #111; }}
  .no-print {{ display: flex; justify-content: space-between; align-items: center; background: #f1f5f9; padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; }}
  .no-print button {{ background: #0f172a; color: #fff; border: 0; padding: 10px 16px; border-radius: 6px; font-weight: 700; cursor: pointer; }}
  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
  .card {{ border: 1.5px dashed #64748b; border-radius: 10px; padding: 14px; text-align: center; page-break-inside: avoid; break-inside: avoid; }}
  .card-header {{ font-size: 0.78rem; color: #475569; text-transform: uppercase; letter-spacing: 0.04em; }}
  .card-session {{ font-size: 0.82rem; color: #64748b; margin-bottom: 6px; }}
  .card-name {{ font-size: 1.15rem; font-weight: 800; margin-bottom: 8px; }}
  .qr-wrap svg {{ width: 140px; height: 140px; }}
  .card-pin {{ font-size: 1.2rem; margin-top: 6px; letter-spacing: 0.12em; }}
  .card-url {{ font-size: 0.78rem; color: #475569; margin-top: 4px; word-break: break-all; }}
  @media print {{
    body {{ padding: 0; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
  <div class="no-print">
    <div><strong>Prístupové QR/PIN karty pre poslancov</strong> — vytlačte a rozstrihajte pred zasadnutím. (Adresa: <code>{esc(base)}/vote</code>)</div>
    <button onclick="window.print()">Tlačiť karty</button>
  </div>
  <div class="grid">{''.join(cards)}</div>
</body>
</html>"""


def render_markdown(db: Database, session_id: int) -> str:
    """Editable Markdown export ready to paste into minutes."""
    sess = db.get_session(session_id)
    if not sess:
        raise KeyError("Zasadnutie neexistuje.")
    councilors = db.list_councilors(session_id)
    votes = db.list_votes(session_id, include_ballots=True)

    lines = [
        f"# {sess['body_name']} – {sess['municipality_name']}",
        f"**Zasadnutie:** {sess['title']} (č. {sess['session_number']})  ",
        f"**Dátum:** {sess['session_date']}  ",
    ]
    if sess.get("chair_name"):
        lines.append(f"**Rokovanie viedol:** {sess['chair_name']}  ")
    lines.append("")
    lines.append("## Prezenčná listina")
    for idx, c in enumerate(councilors, start=1):
        st = "zúčastnil/a sa" if (c["ever_present"] or c["is_present"]) else (
            "nezúčastnil/a sa (ospravedlnený/á)" if c["excused"] else "nezúčastnil/a sa"
        )
        lines.append(f"{idx}. {c['display_name']} – {st}")

    lines.append("")
    lines.append("## Hlasovanie poslancov")
    for v in votes:
        q_label = QUORUM_LABELS[v["quorum_type"]]["label"]
        res = f"č. {v['resolution_number']}" if v.get("resolution_number") else "—"
        lines.extend(
            [
                "",
                f"### Hlasovanie č. {v['vote_number']} (Bod {v['item_number_snapshot']}): {v['title']}",
                f"- **Uznesenie:** {res}",
                f"- **Kvórum:** {q_label} (potrebných ZA: {v['required_for']})",
                f"- **Verdikt:** **{v['verdict_sk']}**",
                f"- **Súhrn:** Za: {v['for_count']} | Proti: {v['against_count']} | Zdržali sa: {v['abstain_count']} | Nehlasovali: {v['not_voted_count']} | Prítomní: {v['present_count_snapshot']}/{v['total_councilors_snapshot']}",
            ]
        )
        for key, heading in [("for", "Za"), ("against", "Proti"), ("abstain", "Zdržali sa"), ("not_voted", "Nehlasovali")]:
            names = _names_by_choice(v, key)
            if names:
                lines.append(f"- **{heading}:** {', '.join(names)}")
        lines.append(f"- **Veta do zápisnice:** `{format_zapisnica_sentence(v)}`")

    return "\n".join(lines) + "\n"


def render_csv(db: Database, session_id: int) -> bytes:
    """UTF-8 with BOM CSV export (Excel-friendly Slovak diacritics)."""
    sess = db.get_session(session_id)
    if not sess:
        raise KeyError("Zasadnutie neexistuje.")
    votes = db.list_votes(session_id, include_ballots=True)

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "Cislo_hlasovania",
            "Cislo_bodu",
            "Nazov_hlasovania",
            "Uznesenie",
            "Kvorum",
            "Potrebnych_ZA",
            "Pritomni",
            "Verdikt",
            "Poslanec",
            "Hlas",
            "Manualny_zasah",
            "Dovod_zasahu",
        ]
    )
    for v in votes:
        q_label = QUORUM_LABELS[v["quorum_type"]]["label"]
        for b in v.get("ballots", []):
            writer.writerow(
                [
                    v["vote_number"],
                    v["item_number_snapshot"],
                    v["title"],
                    v.get("resolution_number") or "",
                    q_label,
                    v["required_for"],
                    v["present_count_snapshot"],
                    v["verdict_sk"],
                    b["display_name"],
                    CHOICE_LABELS_SK.get(b["choice"], b["choice"]),
                    "ANO" if b.get("overridden_by_admin") else "NIE",
                    b.get("override_reason") or "",
                ]
            )
    return buf.getvalue().encode("utf-8-sig")


def render_docx(db: Database, session_id: int) -> bytes:
    """Editable Word (.docx) export matching MČ Furča minutes & voting report."""
    sess = db.get_session(session_id)
    if not sess:
        raise KeyError("Zasadnutie neexistuje.")
    councilors = db.list_councilors(session_id)
    votes = db.list_votes(session_id, include_ballots=True)

    doc = Document()
    h = doc.add_heading(f"{sess['body_name']} – {sess['municipality_name']}", level=1)
    h.runs[0].font.size = Pt(15)

    meta = doc.add_paragraph()
    meta.add_run(f"{sess['title']} (č. {sess['session_number']})").bold = True
    meta.add_run(f"\nDátum: {sess['session_date']}")
    if sess.get("chair_name"):
        meta.add_run(f"   |   Rokovanie viedol: {sess['chair_name']}")

    doc.add_heading("Prezenčná listina", level=2)
    for idx, c in enumerate(councilors, start=1):
        st = "zúčastnil/a sa" if (c["ever_present"] or c["is_present"]) else (
            "nezúčastnil/a sa (ospravedlnený/á)" if c["excused"] else "nezúčastnil/a sa"
        )
        p = doc.add_paragraph(f"{idx}. {c['display_name']}, {st}")
        p.paragraph_format.space_after = Pt(2)

    doc.add_page_break()
    doc.add_heading("HLASOVANIE POSLANCOV", level=2)

    for v in votes:
        q_label = QUORUM_LABELS[v["quorum_type"]]["label"]
        p_head = doc.add_paragraph()
        p_head.paragraph_format.space_before = Pt(8)
        p_head.paragraph_format.space_after = Pt(2)
        r_num = p_head.add_run(f"Číslo hlasovania : {v['vote_number']}   |   Číslo bodu : {v['item_number_snapshot']}\n")
        r_num.bold = True
        r_title = p_head.add_run(f"{v['title']}\n")
        r_title.bold = True
        r_title.font.size = Pt(11)
        res_txt = f"č. {v['resolution_number']}" if v.get("resolution_number") else "—"
        p_head.add_run(f"Uznesenie: {res_txt}   |   Kvórum: {q_label} (potrebných ZA: {v['required_for']})   |   ")
        r_verd = p_head.add_run(v["verdict_sk"] or "UZAVRETÉ")
        r_verd.bold = True
        r_verd.font.color.rgb = RGBColor(0x16, 0x65, 0x34) if v["passed"] else RGBColor(0x99, 0x1B, 0x1B)

        p_counts = doc.add_paragraph(
            f"Poslanci hlasovali nasledovne: Za: {v['for_count']} | Proti: {v['against_count']} | "
            f"Zdržali sa: {v['abstain_count']} | Nehlasovali: {v['not_voted_count']} | "
            f"Prítomní: {v['present_count_snapshot']} / {v['total_councilors_snapshot']}"
        )
        p_counts.paragraph_format.space_after = Pt(2)

        for key, heading in [("for", "Za"), ("against", "Proti"), ("abstain", "Zdržali sa"), ("not_voted", "Nehlasovali")]:
            names = _names_by_choice(v, key)
            if names:
                pn = doc.add_paragraph()
                pn.paragraph_format.space_after = Pt(1)
                pn.add_run(f"{heading}: ").bold = True
                pn.add_run(", ".join(names))

        pz = doc.add_paragraph()
        pz.paragraph_format.space_after = Pt(6)
        rz = pz.add_run(format_zapisnica_sentence(v))
        rz.italic = True

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
