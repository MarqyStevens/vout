"""End-to-end API, timer auto-close, virtual card presence, audit override, and export tests."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from vout.app import create_app


ADMIN_HEADERS = {"X-Admin-Pin": "9999"}


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(db_path=tmp_path / "test_vout.db", admin_pin="9999", seed_demo=True)
    return TestClient(app)


def test_demo_seed_and_pages_load(tmp_path: Path):
    with make_client(tmp_path) as client:
        for path in ("/", "/vote", "/admin", "/display", "/api/health"):
            r = client.get(path)
            assert r.status_code == 200

        state = client.get("/api/display/state").json()
        assert state["session"]["total_councilors"] == 13
        assert state["attendance"]["present_count"] == 10
        assert state["attendance"]["min_present"] == 7
        assert state["attendance"]["quorate"] is True
        # Public state must never expose PINs or tokens
        for c in state["councilors"]:
            assert "pin" not in c
            assert "token" not in c


def test_admin_auth_guard(tmp_path: Path):
    with make_client(tmp_path) as client:
        assert client.get("/api/admin/state").status_code == 401
        assert client.get("/api/admin/state", headers={"X-Admin-Pin": "0000"}).status_code == 401
        r = client.get("/api/admin/state", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert len(r.json()["state"]["councilors"]) == 13


def test_card_presence_blind_display_countdown_autoclose_and_override(tmp_path: Path):
    with make_client(tmp_path) as client:
        admin_state = client.get("/api/admin/state", headers=ADMIN_HEADERS).json()["state"]
        sid = admin_state["session"]["id"]
        councilors = admin_state["councilors"]

        # Councilor 0 (present) logs in via PIN and pulls card out, then puts it back
        c0 = councilors[0]
        auth = client.post("/api/vote/auth", json={"pin": c0["pin"]}).json()
        tok0 = auth["token"]
        assert auth["state"]["me"]["is_present"] is True

        r_out = client.post("/api/vote/presence", json={"token": tok0, "is_present": False})
        assert r_out.status_code == 200
        assert r_out.json()["attendance"]["present_count"] == 9

        r_in = client.post("/api/vote/presence", json={"token": tok0, "is_present": True})
        assert r_in.status_code == 200
        assert r_in.json()["attendance"]["present_count"] == 10

        # Open a 1-second countdown VZN vote (three_fifths_present -> 10 present -> need 6 FOR)
        v_open = client.post(
            f"/api/admin/sessions/{sid}/votes/open",
            headers=ADMIN_HEADERS,
            json={
                "title": "Návrh VZN č. 1/2026",
                "item_number_snapshot": "4",
                "quorum_type": "three_fifths_present",
                "duration_sec": 2,
            },
        )
        assert v_open.status_code == 200
        vote = v_open.json()
        vid = vote["id"]
        assert vote["vote_number"] == 1
        assert vote["required_for"] == 6

        # Pulling card out during open vote MUST be blocked (409)
        r_blocked = client.post("/api/vote/presence", json={"token": tok0, "is_present": False})
        assert r_blocked.status_code == 409

        # Cast 5 FOR, 2 AGAINST, 1 ABSTAIN (2 present remain NOT_VOTED -> fails 5 < 6)
        present_councilors = [c for c in councilors if c["is_present"]]
        for c in present_councilors[:5]:
            assert client.post("/api/vote/cast", json={"token": c["token"], "vote_id": vid, "choice": "for"}).status_code == 200
        for c in present_councilors[5:7]:
            assert client.post("/api/vote/cast", json={"token": c["token"], "vote_id": vid, "choice": "against"}).status_code == 200
        assert client.post("/api/vote/cast", json={"token": present_councilors[7]["token"], "vote_id": vid, "choice": "abstain"}).status_code == 200

        # Absent councilor cannot vote
        absent_c = [c for c in councilors if not c["is_present"]][0]
        assert client.post("/api/vote/cast", json={"token": absent_c["token"], "vote_id": vid, "choice": "for"}).status_code == 409

        # While OPEN, /display must hide individual choices and show has_voted=True only!
        disp_open = client.get("/api/display/state").json()
        cv = disp_open["current_vote"]
        assert cv["status"] == "open"
        assert cv["for_count"] is None
        assert cv["voted_count"] == 8
        assert all(b["choice"] is None for b in cv["ballots"])
        assert sum(1 for b in cv["ballots"] if b["has_voted"]) == 8

        # Wait for server countdown timer to auto-close the vote
        time.sleep(2.3)

        disp_closed = client.get("/api/display/state").json()
        assert disp_closed["current_vote"] is None
        lcv = disp_closed["last_closed_vote"]
        assert lcv["status"] == "closed"
        assert lcv["for_count"] == 5
        assert lcv["against_count"] == 2
        assert lcv["abstain_count"] == 1
        assert lcv["not_voted_count"] == 2
        assert lcv["absent_count"] == 3
        assert lcv["passed"] == 0
        assert lcv["verdict_sk"] == "NESCHVÁLENÉ"

        # Manual override without reason must fail (400)
        assert client.post(
            f"/api/admin/votes/{vid}/override",
            headers=ADMIN_HEADERS,
            json={"councilor_id": present_councilors[8]["id"], "choice": "for", "reason": "   "},
        ).status_code == 400

        # Manual override with reason flips 1 NOT_VOTED -> FOR => 6/6 => SCHVÁLENÉ!
        ov = client.post(
            f"/api/admin/votes/{vid}/override",
            headers=ADMIN_HEADERS,
            json={
                "councilor_id": present_councilors[8]["id"],
                "choice": "for",
                "reason": "Výpadok mobilu – verejné hlasovanie zdvihnutím ruky",
            },
        )
        assert ov.status_code == 200
        ov_vote = ov.json()
        assert ov_vote["for_count"] == 6
        assert ov_vote["not_voted_count"] == 1
        assert ov_vote["passed"] == 1
        assert ov_vote["verdict_sk"] == "SCHVÁLENÉ"

        # Assign auto resolution number (1/YYYY)
        res_r = client.post(f"/api/admin/votes/{vid}/resolution", headers=ADMIN_HEADERS, json={"auto_next": True})
        assert res_r.status_code == 200
        assert res_r.json()["resolution_number"].startswith("1/")

        # Repeat vote creates vote #2 without deleting vote #1
        v2 = client.post(
            f"/api/admin/sessions/{sid}/votes/open",
            headers=ADMIN_HEADERS,
            json={
                "title": "Návrh VZN č. 1/2026 – opakované hlasovanie",
                "item_number_snapshot": "4",
                "quorum_type": "three_fifths_present",
                "duration_sec": 0,
                "repeated_from_vote_id": vid,
            },
        ).json()
        assert v2["vote_number"] == 2
        assert client.post(f"/api/admin/votes/{v2['id']}/close", headers=ADMIN_HEADERS).status_code == 200

        # Audit log recorded the override and both votes
        audits = client.get(f"/api/admin/sessions/{sid}/audit", headers=ADMIN_HEADERS).json()
        actions = {a["action"] for a in audits}
        assert {"vote_opened", "vote_cast", "vote_closed", "admin_vote_override", "resolution_assigned"} <= actions

        # Exports: HTML, MD, CSV (BOM), DOCX (valid zip), QR cards (SVG)
        r_html = client.get(f"/api/admin/sessions/{sid}/export/html", headers=ADMIN_HEADERS)
        assert r_html.status_code == 200 and "HLASOVANIE POSLANCOV" in r_html.text and "Prezenčná listina" in r_html.text

        r_md = client.get(f"/api/admin/sessions/{sid}/export/md", headers=ADMIN_HEADERS)
        assert r_md.status_code == 200 and "Hlasovanie č. 1" in r_md.text

        r_csv = client.get(f"/api/admin/sessions/{sid}/export/csv", headers=ADMIN_HEADERS)
        assert r_csv.status_code == 200 and r_csv.content.startswith(b"\xef\xbb\xbf")

        r_docx = client.get(f"/api/admin/sessions/{sid}/export/docx", headers=ADMIN_HEADERS)
        assert r_docx.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r_docx.content)) as zf:
            assert "word/document.xml" in zf.namelist()

        r_qr = client.get(f"/api/admin/sessions/{sid}/qr-cards", headers=ADMIN_HEADERS)
        assert r_qr.status_code == 200 and "<svg" in r_qr.text


def test_websocket_realtime_display_and_voter_sync(tmp_path: Path):
    with make_client(tmp_path) as client:
        admin_state = client.get("/api/admin/state", headers=ADMIN_HEADERS).json()["state"]
        sid = admin_state["session"]["id"]
        c0 = admin_state["councilors"][0]

        with client.websocket_connect("/ws/display") as ws_disp, client.websocket_connect(
            f"/ws/vote/{c0['token']}"
        ) as ws_vote:
            init_disp = ws_disp.receive_json()
            init_vote = ws_vote.receive_json()
            assert init_disp["type"] == "state"
            assert init_vote["data"]["me"]["id"] == c0["id"]

            # Open vote -> both sockets receive live update
            v = client.post(
                f"/api/admin/sessions/{sid}/votes/open",
                headers=ADMIN_HEADERS,
                json={"title": "WS test", "item_number_snapshot": "1", "quorum_type": "majority_present", "duration_sec": 0},
            ).json()

            upd_disp = ws_disp.receive_json()
            upd_vote = ws_vote.receive_json()
            assert upd_disp["data"]["current_vote"]["id"] == v["id"]
            assert upd_vote["data"]["current_vote"]["id"] == v["id"]

            # Voter casts FOR -> display sees has_voted=True, choice=None
            client.post("/api/vote/cast", json={"token": c0["token"], "vote_id": v["id"], "choice": "for"})
            cast_disp = ws_disp.receive_json()
            b0 = next(b for b in cast_disp["data"]["current_vote"]["ballots"] if b["councilor_id"] == c0["id"])
            assert b0["has_voted"] is True
            assert b0["choice"] is None

