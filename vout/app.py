"""FastAPI backend, REST API, WebSocket endpoints, and static HTML serving for vout."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ADMIN_PIN, DB_PATH
from .db import Database
from .exports import (
    format_zapisnica_sentence,
    render_csv,
    render_docx,
    render_hlasovanie_html,
    render_markdown,
    render_qr_cards_html,
)
from .ws import RealtimeHub

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ---------------- Pydantic Request Models ----------------

class AdminLoginRequest(BaseModel):
    pin: str


class VoterAuthRequest(BaseModel):
    token: str | None = None
    pin: str | None = None
    session_id: int | None = None


class VoterPresenceRequest(BaseModel):
    token: str
    is_present: bool


class VoterCastRequest(BaseModel):
    token: str
    vote_id: int
    choice: str


class SessionCreateRequest(BaseModel):
    title: str
    session_date: str
    municipality_name: str = "MČ Košice – Dargovských hrdinov"
    body_name: str = "Miestne zastupiteľstvo"
    session_number: str = "1"
    chair_name: str = ""
    total_councilors: int = Field(default=13, ge=1, le=200)
    default_duration_sec: int = Field(default=15, ge=0, le=600)
    reveal_live_votes: bool = False
    next_resolution_seq: int = Field(default=1, ge=1)
    resolution_year: int | None = None


class SessionUpdateRequest(BaseModel):
    municipality_name: str | None = None
    body_name: str | None = None
    title: str | None = None
    session_number: str | None = None
    session_date: str | None = None
    chair_name: str | None = None
    total_councilors: int | None = None
    default_duration_sec: int | None = None
    reveal_live_votes: bool | None = None
    next_resolution_seq: int | None = None
    resolution_year: int | None = None


class CouncilorCreateRequest(BaseModel):
    first_name: str
    last_name: str
    title: str = ""
    district: str = ""
    pin: str | None = None


class AdminPresenceRequest(BaseModel):
    is_present: bool
    excused: bool | None = None
    reason: str = "Zásah zapisovateľa"


class AgendaCreateRequest(BaseModel):
    item_number: str
    title: str
    description: str = ""
    default_quorum: str = "majority_present"


class AgendaUpdateRequest(BaseModel):
    item_number: str | None = None
    title: str | None = None
    description: str | None = None
    default_quorum: str | None = None


class AgendaReorderRequest(BaseModel):
    ordered_ids: list[int]


class ActiveAgendaRequest(BaseModel):
    item_id: int | None = None


class VoteOpenRequest(BaseModel):
    title: str
    quorum_type: str = "majority_present"
    duration_sec: int | None = None
    agenda_item_id: int | None = None
    item_number_snapshot: str = ""
    repeated_from_vote_id: int | None = None
    note: str = ""


class VoteExtendRequest(BaseModel):
    add_seconds: int = Field(default=10, ge=1, le=300)


class BallotOverrideRequest(BaseModel):
    councilor_id: int
    choice: str
    reason: str


class ResolutionAssignRequest(BaseModel):
    resolution_number: str | None = None
    auto_next: bool = False


def create_app(db_path: Path | str | None = None, admin_pin: str | None = None, seed_demo: bool = True) -> FastAPI:
    db = Database(db_path or DB_PATH)
    if seed_demo:
        db.seed_demo_if_empty()
    hub = RealtimeHub(db)
    expected_admin_pin = admin_pin if admin_pin is not None else ADMIN_PIN

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await hub.resume_pending_timers()
        try:
            yield
        finally:
            hub.cancel_all_timers()

    app = FastAPI(title="vout – Elektronické hlasovanie zastupiteľstva", lifespan=lifespan)
    app.state.db = db
    app.state.hub = hub

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def require_admin(
        request: Request,
        x_admin_pin: str | None = Header(default=None),
    ) -> str:
        pin = x_admin_pin or request.cookies.get("vout_admin_pin")
        if pin != expected_admin_pin:
            raise HTTPException(status_code=401, detail="Neplatný admin PIN.")
        return "Zapisovateľ"

    # ---------------- HTML Pages ----------------

    @app.get("/", response_class=HTMLResponse)
    async def page_index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/vote", response_class=HTMLResponse)
    async def page_vote():
        return FileResponse(STATIC_DIR / "vote.html")

    @app.get("/admin", response_class=HTMLResponse)
    async def page_admin():
        return FileResponse(STATIC_DIR / "admin.html")

    @app.get("/display", response_class=HTMLResponse)
    async def page_display():
        return FileResponse(STATIC_DIR / "display.html")

    # ---------------- Public / Display API ----------------

    @app.get("/api/health")
    async def api_health():
        return {"status": "ok"}

    @app.get("/api/display/state")
    async def api_display_state(session_id: int | None = None):
        return db.build_public_state(session_id=session_id, for_admin=False)

    # ---------------- Voter (/vote) API ----------------

    @app.post("/api/vote/auth")
    async def api_vote_auth(body: VoterAuthRequest):
        c = None
        if body.token:
            c = db.auth_councilor_by_token(body.token)
        elif body.pin:
            c = db.auth_councilor_by_pin(body.pin, session_id=body.session_id)
        if not c:
            raise HTTPException(status_code=401, detail="Neplatný PIN alebo QR odkaz.")
        state = db.build_councilor_state(int(c["id"]))
        return {"token": c["token"], "councilor_id": c["id"], "state": state}

    @app.get("/api/vote/state")
    async def api_vote_state(token: str = Query(...)):
        with db.connect() as conn:
            row = conn.execute("SELECT id FROM councilors WHERE token = ?", (token.strip(),)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Neplatný token poslanca.")
        return db.build_councilor_state(int(row["id"]))

    @app.post("/api/vote/presence")
    async def api_vote_presence(body: VoterPresenceRequest):
        with db.connect() as conn:
            row = conn.execute("SELECT id FROM councilors WHERE token = ?", (body.token.strip(),)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Neplatný token poslanca.")
        c = db.get_councilor(int(row["id"]))
        assert c is not None
        try:
            updated = db.set_councilor_presence(
                int(c["id"]),
                body.is_present,
                actor_type="councilor",
                actor_name=c["display_name"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=int(updated["session_id"]))
        return db.build_councilor_state(int(updated["id"]))

    @app.post("/api/vote/cast")
    async def api_vote_cast(body: VoterCastRequest):
        with db.connect() as conn:
            row = conn.execute("SELECT id, session_id FROM councilors WHERE token = ?", (body.token.strip(),)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Neplatný token poslanca.")
        cid = int(row["id"])
        sid = int(row["session_id"])
        try:
            db.cast_ballot(body.vote_id, cid, body.choice)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=sid)
        return db.build_councilor_state(cid)

    # ---------------- Admin (/admin) Auth & State ----------------

    @app.post("/api/admin/login")
    async def api_admin_login(body: AdminLoginRequest, response: Response):
        if body.pin != expected_admin_pin:
            raise HTTPException(status_code=401, detail="Nesprávny PIN zapisovateľa.")
        response.set_cookie("vout_admin_pin", body.pin, httponly=True, samesite="lax", max_age=86400)
        return {"ok": True}

    @app.get("/api/admin/state")
    async def api_admin_state(session_id: int | None = None, _admin: str = Depends(require_admin)):
        return {
            "sessions": db.list_sessions(),
            "state": db.build_public_state(session_id=session_id, for_admin=True),
        }

    # ---------------- Admin Sessions ----------------

    @app.post("/api/admin/sessions")
    async def api_create_session(body: SessionCreateRequest, admin: str = Depends(require_admin)):
        try:
            sess = db.create_session(**body.model_dump(), activate=True, actor_name=admin)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=int(sess["id"]))
        return sess

    @app.post("/api/admin/sessions/{session_id}/activate")
    async def api_activate_session(session_id: int, admin: str = Depends(require_admin)):
        try:
            sess = db.set_active_session(session_id, actor_name=admin)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=session_id)
        return sess

    @app.patch("/api/admin/sessions/{session_id}")
    async def api_update_session(session_id: int, body: SessionUpdateRequest, admin: str = Depends(require_admin)):
        try:
            sess = db.update_session(session_id, body.model_dump(exclude_none=True), actor_name=admin)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=session_id)
        return sess

    # ---------------- Admin Councilors ----------------

    @app.post("/api/admin/sessions/{session_id}/councilors")
    async def api_add_councilor(session_id: int, body: CouncilorCreateRequest, admin: str = Depends(require_admin)):
        try:
            c = db.add_councilor(session_id, **body.model_dump(), actor_name=admin)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=session_id)
        return c

    @app.delete("/api/admin/councilors/{councilor_id}")
    async def api_delete_councilor(councilor_id: int, admin: str = Depends(require_admin)):
        c = db.get_councilor(councilor_id)
        if not c:
            raise HTTPException(status_code=404, detail="Poslanec neexistuje.")
        sid = int(c["session_id"])
        try:
            db.delete_councilor(councilor_id, actor_name=admin)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=sid)
        return {"ok": True}

    @app.post("/api/admin/councilors/{councilor_id}/presence")
    async def api_admin_presence(councilor_id: int, body: AdminPresenceRequest, admin: str = Depends(require_admin)):
        try:
            updated = db.set_councilor_presence(
                councilor_id,
                body.is_present,
                actor_type="admin",
                actor_name=admin,
                reason=body.reason,
                excused=body.excused,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=int(updated["session_id"]))
        return updated

    # ---------------- Admin Agenda ----------------

    @app.post("/api/admin/sessions/{session_id}/agenda")
    async def api_add_agenda(session_id: int, body: AgendaCreateRequest, admin: str = Depends(require_admin)):
        try:
            item = db.add_agenda_item(session_id, **body.model_dump(), actor_name=admin)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=session_id)
        return item

    @app.patch("/api/admin/agenda/{item_id}")
    async def api_update_agenda(item_id: int, body: AgendaUpdateRequest, admin: str = Depends(require_admin)):
        try:
            item = db.update_agenda_item(item_id, body.model_dump(exclude_none=True), actor_name=admin)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=int(item["session_id"]))
        return item

    @app.delete("/api/admin/agenda/{item_id}")
    async def api_delete_agenda(item_id: int, admin: str = Depends(require_admin)):
        with db.connect() as conn:
            row = conn.execute("SELECT session_id FROM agenda_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bod programu neexistuje.")
        sid = int(row["session_id"])
        db.delete_agenda_item(item_id, actor_name=admin)
        await hub.broadcast_state(session_id=sid)
        return {"ok": True}

    @app.post("/api/admin/sessions/{session_id}/agenda/reorder")
    async def api_reorder_agenda(session_id: int, body: AgendaReorderRequest, admin: str = Depends(require_admin)):
        items = db.reorder_agenda_items(session_id, body.ordered_ids, actor_name=admin)
        await hub.broadcast_state(session_id=session_id)
        return items

    @app.post("/api/admin/sessions/{session_id}/agenda/active")
    async def api_set_active_agenda(session_id: int, body: ActiveAgendaRequest, admin: str = Depends(require_admin)):
        try:
            db.set_active_agenda_item(session_id, body.item_id, actor_name=admin)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=session_id)
        return {"ok": True}

    # ---------------- Admin Votes ----------------

    @app.post("/api/admin/sessions/{session_id}/votes/open")
    async def api_open_vote(session_id: int, body: VoteOpenRequest, admin: str = Depends(require_admin)):
        try:
            vote = db.open_vote(session_id, **body.model_dump(), actor_name=admin)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        hub.schedule_vote_close(int(vote["id"]), session_id, vote.get("closes_at"))
        await hub.broadcast_state(session_id=session_id)
        return db.get_vote_with_ballots(int(vote["id"]))

    @app.post("/api/admin/votes/{vote_id}/extend")
    async def api_extend_vote(vote_id: int, body: VoteExtendRequest, admin: str = Depends(require_admin)):
        try:
            vote = db.extend_vote(vote_id, body.add_seconds, actor_name=admin)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        hub.schedule_vote_close(vote_id, int(vote["session_id"]), vote.get("closes_at"))
        await hub.broadcast_state(session_id=int(vote["session_id"]))
        return db.get_vote_with_ballots(vote_id)

    @app.post("/api/admin/votes/{vote_id}/close")
    async def api_close_vote(vote_id: int, admin: str = Depends(require_admin)):
        hub.cancel_timer(vote_id)
        try:
            vote = db.close_vote(vote_id, actor_type="admin", actor_name=admin)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=int(vote["session_id"]))
        return db.get_vote_with_ballots(vote_id)

    @app.post("/api/admin/votes/{vote_id}/override")
    async def api_override_ballot(vote_id: int, body: BallotOverrideRequest, admin: str = Depends(require_admin)):
        try:
            vote = db.admin_override_ballot(vote_id, body.councilor_id, body.choice, body.reason, actor_name=admin)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=int(vote["session_id"]))
        return db.get_vote_with_ballots(vote_id)

    @app.post("/api/admin/votes/{vote_id}/resolution")
    async def api_assign_resolution(vote_id: int, body: ResolutionAssignRequest, admin: str = Depends(require_admin)):
        try:
            vote = db.assign_resolution_number(
                vote_id, body.resolution_number, auto_next=body.auto_next, actor_name=admin
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await hub.broadcast_state(session_id=int(vote["session_id"]))
        return db.get_vote_with_ballots(vote_id)

    @app.get("/api/admin/sessions/{session_id}/audit")
    async def api_audit_logs(session_id: int, limit: int = 200, _admin: str = Depends(require_admin)):
        return db.list_audit_logs(session_id=session_id, limit=limit)

    @app.get("/api/admin/votes/{vote_id}/zapisnica-line")
    async def api_zapisnica_line(vote_id: int, _admin: str = Depends(require_admin)):
        v = db.get_vote_with_ballots(vote_id)
        if not v:
            raise HTTPException(status_code=404, detail="Hlasovanie neexistuje.")
        return {"text": format_zapisnica_sentence(v)}

    # ---------------- Exports & QR Cards ----------------

    @app.get("/api/admin/sessions/{session_id}/qr-cards", response_class=HTMLResponse)
    async def api_qr_cards(session_id: int, request: Request, _admin: str = Depends(require_admin)):
        base_url = str(request.base_url).rstrip("/")
        try:
            return HTMLResponse(render_qr_cards_html(db, session_id, base_url))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/admin/sessions/{session_id}/export/html", response_class=HTMLResponse)
    async def api_export_html(session_id: int, _admin: str = Depends(require_admin)):
        try:
            return HTMLResponse(render_hlasovanie_html(db, session_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/admin/sessions/{session_id}/export/md", response_class=PlainTextResponse)
    async def api_export_md(session_id: int, _admin: str = Depends(require_admin)):
        try:
            content = render_markdown(db, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return PlainTextResponse(
            content,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="hlasovanie-zasadnutie-{session_id}.md"'},
        )

    @app.get("/api/admin/sessions/{session_id}/export/csv")
    async def api_export_csv(session_id: int, _admin: str = Depends(require_admin)):
        try:
            data = render_csv(db, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="hlasovanie-zasadnutie-{session_id}.csv"'},
        )

    @app.get("/api/admin/sessions/{session_id}/export/docx")
    async def api_export_docx(session_id: int, _admin: str = Depends(require_admin)):
        try:
            data = render_docx(db, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(
            iter([data]),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="hlasovanie-zasadnutie-{session_id}.docx"'},
        )

    # ---------------- WebSockets ----------------

    @app.websocket("/ws/display")
    async def ws_display(ws: WebSocket):
        await hub.connect_display(ws)
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            hub.disconnect(ws)

    @app.websocket("/ws/admin")
    async def ws_admin(ws: WebSocket, pin: str | None = Query(default=None)):
        cookie_pin = ws.cookies.get("vout_admin_pin")
        if (pin or cookie_pin) != expected_admin_pin:
            await ws.close(code=4401)
            return
        await hub.connect_admin(ws)
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            hub.disconnect(ws)

    @app.websocket("/ws/vote/{token}")
    async def ws_vote(ws: WebSocket, token: str):
        with db.connect() as conn:
            row = conn.execute("SELECT id FROM councilors WHERE token = ?", (token.strip(),)).fetchone()
        if not row:
            await ws.close(code=4401)
            return
        await hub.connect_voter(ws, int(row["id"]))
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            hub.disconnect(ws)

    return app


app = create_app()
