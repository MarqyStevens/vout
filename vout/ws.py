"""Real-time WebSocket hub and server-side vote countdown timer manager."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from .db import Database, parse_iso


class RealtimeHub:
    """Manages WebSocket clients (display, admin, councilors) and countdown auto-close tasks."""

    def __init__(self, db: Database):
        self.db = db
        self.display_clients: set[WebSocket] = set()
        self.admin_clients: set[WebSocket] = set()
        self.vote_clients: dict[WebSocket, int] = {}  # ws -> councilor_id
        self._timer_tasks: dict[int, asyncio.Task[None]] = {}  # vote_id -> task

    async def connect_display(self, ws: WebSocket) -> None:
        await ws.accept()
        self.display_clients.add(ws)
        await self._send_safe(ws, {"type": "state", "data": self.db.build_public_state(for_admin=False)})

    async def connect_admin(self, ws: WebSocket) -> None:
        await ws.accept()
        self.admin_clients.add(ws)
        await self._send_safe(ws, {"type": "state", "data": self.db.build_public_state(for_admin=True)})

    async def connect_voter(self, ws: WebSocket, councilor_id: int) -> None:
        await ws.accept()
        self.vote_clients[ws] = councilor_id
        state = self.db.build_councilor_state(councilor_id)
        if state:
            await self._send_safe(ws, {"type": "state", "data": state})

    def disconnect(self, ws: WebSocket) -> None:
        self.display_clients.discard(ws)
        self.admin_clients.discard(ws)
        self.vote_clients.pop(ws, None)

    async def _send_safe(self, ws: WebSocket, payload: dict[str, Any]) -> bool:
        try:
            await ws.send_json(payload)
            return True
        except Exception:
            self.disconnect(ws)
            return False

    async def broadcast_state(self, session_id: int | None = None) -> None:
        """Broadcast fresh tailored state to all display, admin, and voter clients."""
        public_state = self.db.build_public_state(session_id=session_id, for_admin=False)
        admin_state = self.db.build_public_state(session_id=session_id, for_admin=True)

        coros = []
        for ws in list(self.display_clients):
            coros.append(self._send_safe(ws, {"type": "state", "data": public_state}))
        for ws in list(self.admin_clients):
            coros.append(self._send_safe(ws, {"type": "state", "data": admin_state}))
        for ws, cid in list(self.vote_clients.items()):
            c_state = self.db.build_councilor_state(cid)
            if c_state:
                coros.append(self._send_safe(ws, {"type": "state", "data": c_state}))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    # ---------------- Countdown Auto-Close ----------------

    def cancel_timer(self, vote_id: int) -> None:
        task = self._timer_tasks.pop(vote_id, None)
        if task and not task.done():
            task.cancel()

    def schedule_vote_close(self, vote_id: int, session_id: int, closes_at_iso: str | None) -> None:
        self.cancel_timer(vote_id)
        if not closes_at_iso:
            return
        closes_dt = parse_iso(closes_at_iso)
        if not closes_dt:
            return

        async def _wait_and_close() -> None:
            try:
                delay = (closes_dt - datetime.now(timezone.utc)).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)
                self.db.close_vote(vote_id, actor_type="system", actor_name="Časovač (odpočet)")
                self._timer_tasks.pop(vote_id, None)
                await self.broadcast_state(session_id=session_id)
            except asyncio.CancelledError:
                return
            except Exception:
                self._timer_tasks.pop(vote_id, None)

        self._timer_tasks[vote_id] = asyncio.create_task(_wait_and_close())

    async def resume_pending_timers(self) -> None:
        """Resume countdowns for any open votes after a server restart."""
        for sess in self.db.list_sessions():
            sid = int(sess["id"])
            for v in self.db.list_votes(sid, include_ballots=False):
                if v["status"] == "open" and v.get("closes_at"):
                    closes_dt = parse_iso(v["closes_at"])
                    if closes_dt and closes_dt <= datetime.now(timezone.utc):
                        self.db.close_vote(int(v["id"]), actor_type="system", actor_name="Časovač (po reštarte)")
                    else:
                        self.schedule_vote_close(int(v["id"]), sid, v["closes_at"])

    def cancel_all_timers(self) -> None:
        for vid in list(self._timer_tasks.keys()):
            self.cancel_timer(vid)
