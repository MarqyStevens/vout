"""SQLite persistence layer, schema initialization, domain transactions, and append-only audit log."""

from __future__ import annotations

import json
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .quorum import (
    QUORUM_LABELS,
    VALID_BALLOT_STATES,
    VALID_QUORUM_TYPES,
    VALID_VOTE_CHOICES,
    evaluate_vote,
    is_quorate,
    min_present_for_quorum,
    required_votes_for,
)

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipality_name TEXT NOT NULL DEFAULT 'MČ Košice – Dargovských hrdinov',
    body_name TEXT NOT NULL DEFAULT 'Miestne zastupiteľstvo',
    title TEXT NOT NULL,
    session_number TEXT NOT NULL DEFAULT '1',
    session_date TEXT NOT NULL,
    chair_name TEXT NOT NULL DEFAULT '',
    total_councilors INTEGER NOT NULL DEFAULT 13,
    default_duration_sec INTEGER NOT NULL DEFAULT 15,
    reveal_live_votes INTEGER NOT NULL DEFAULT 0,
    next_resolution_seq INTEGER NOT NULL DEFAULT 1,
    resolution_year INTEGER NOT NULL DEFAULT 2026,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS councilors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    district TEXT NOT NULL DEFAULT '',
    pin TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    is_present INTEGER NOT NULL DEFAULT 0,
    ever_present INTEGER NOT NULL DEFAULT 0,
    excused INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(session_id, pin)
);

CREATE TABLE IF NOT EXISTS agenda_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    item_number TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    default_quorum TEXT NOT NULL DEFAULT 'majority_present',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agenda_item_id INTEGER REFERENCES agenda_items(id) ON DELETE SET NULL,
    vote_number INTEGER NOT NULL,
    item_number_snapshot TEXT NOT NULL,
    title TEXT NOT NULL,
    quorum_type TEXT NOT NULL,
    duration_sec INTEGER NOT NULL DEFAULT 15,
    status TEXT NOT NULL DEFAULT 'open',
    opened_at TEXT NOT NULL,
    closes_at TEXT,
    closed_at TEXT,
    total_councilors_snapshot INTEGER NOT NULL,
    present_count_snapshot INTEGER NOT NULL,
    quorum_met INTEGER NOT NULL DEFAULT 1,
    required_for INTEGER NOT NULL,
    for_count INTEGER NOT NULL DEFAULT 0,
    against_count INTEGER NOT NULL DEFAULT 0,
    abstain_count INTEGER NOT NULL DEFAULT 0,
    not_voted_count INTEGER NOT NULL DEFAULT 0,
    absent_count INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    verdict_sk TEXT NOT NULL DEFAULT '',
    resolution_number TEXT,
    repeated_from_vote_id INTEGER REFERENCES votes(id) ON DELETE SET NULL,
    note TEXT NOT NULL DEFAULT '',
    UNIQUE(session_id, vote_number)
);

CREATE TABLE IF NOT EXISTS vote_ballots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vote_id INTEGER NOT NULL REFERENCES votes(id) ON DELETE CASCADE,
    councilor_id INTEGER NOT NULL REFERENCES councilors(id) ON DELETE CASCADE,
    was_present INTEGER NOT NULL DEFAULT 1,
    choice TEXT NOT NULL DEFAULT 'not_voted',
    cast_at TEXT,
    overridden_by_admin INTEGER NOT NULL DEFAULT 0,
    override_reason TEXT NOT NULL DEFAULT '',
    UNIQUE(vote_id, councilor_id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    timestamp TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id INTEGER,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_councilors_session ON councilors(session_id);
CREATE INDEX IF NOT EXISTS idx_agenda_session ON agenda_items(session_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_votes_session ON votes(session_id, vote_number);
CREATE INDEX IF NOT EXISTS idx_ballots_vote ON vote_ballots(vote_id);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_logs(session_id, id DESC);
"""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None = None) -> str:
    return (dt or now_utc()).isoformat(timespec="seconds")


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts)


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def councilor_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_strip_accents(row["last_name"]), _strip_accents(row["first_name"]))


def format_councilor_name(row: dict[str, Any], last_first: bool = True) -> str:
    title = (row.get("title") or "").strip()
    if last_first:
        base = f"{row['last_name']} {row['first_name']}".strip()
        return f"{base}, {title}" if title else base
    base = f"{row['first_name']} {row['last_name']}".strip()
    return f"{title} {base}" if title else base


def generate_pin(existing_pins: set[str], length: int = 4) -> str:
    low = 10 ** (length - 1)
    high = (10**length) - 1
    for _ in range(500):
        pin = str(secrets.randbelow(high - low + 1) + low)
        if pin not in existing_pins:
            existing_pins.add(pin)
            return pin
    raise RuntimeError("Failed to generate unique PIN")


def generate_token() -> str:
    return secrets.token_urlsafe(12)


class Database:
    """SQLite database facade for vout."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def log_audit(
        self,
        conn: sqlite3.Connection,
        session_id: int | None,
        actor_type: str,
        actor_name: str,
        action: str,
        entity_type: str = "",
        entity_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_logs (session_id, timestamp, actor_type, actor_name, action, entity_type, entity_id, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                iso_utc(),
                actor_type,
                actor_name,
                action,
                entity_type,
                entity_id,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )

    # ---------------- Sessions ----------------

    def create_session(
        self,
        title: str,
        session_date: str,
        municipality_name: str = "MČ Košice – Dargovských hrdinov",
        body_name: str = "Miestne zastupiteľstvo",
        session_number: str = "1",
        chair_name: str = "",
        total_councilors: int = 13,
        default_duration_sec: int = 15,
        reveal_live_votes: bool = False,
        next_resolution_seq: int = 1,
        resolution_year: int | None = None,
        activate: bool = True,
        actor_name: str = "Zapisovateľ",
    ) -> dict[str, Any]:
        if total_councilors < 1:
            raise ValueError("Počet poslancov musí byť aspoň 1.")
        if default_duration_sec < 0:
            raise ValueError("Dĺžka odpočtu nemôže byť záporná.")
        year = resolution_year or int(session_date[:4]) if len(session_date) >= 4 else now_utc().year
        with self.connect() as conn:
            if activate:
                conn.execute("UPDATE sessions SET is_active = 0")
            cur = conn.execute(
                """
                INSERT INTO sessions (
                    municipality_name, body_name, title, session_number, session_date,
                    chair_name, total_councilors, default_duration_sec, reveal_live_votes,
                    next_resolution_seq, resolution_year, is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    municipality_name.strip(),
                    body_name.strip(),
                    title.strip(),
                    str(session_number).strip(),
                    session_date.strip(),
                    chair_name.strip(),
                    int(total_councilors),
                    int(default_duration_sec),
                    1 if reveal_live_votes else 0,
                    int(next_resolution_seq),
                    int(year),
                    1 if activate else 0,
                    iso_utc(),
                ),
            )
            sid = int(cur.lastrowid)
            self.log_audit(
                conn,
                sid,
                "admin",
                actor_name,
                "session_created",
                "session",
                sid,
                {"title": title, "total_councilors": total_councilors, "session_date": session_date},
            )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
            return dict(row)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY is_active DESC, id DESC").fetchall()
            return [dict(r) for r in rows]

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(row) if row else None

    def get_active_session(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE is_active = 1 ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                row = conn.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def set_active_session(self, session_id: int, actor_name: str = "Zapisovateľ") -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                raise KeyError("Zasadnutie neexistuje.")
            conn.execute("UPDATE sessions SET is_active = 0")
            conn.execute("UPDATE sessions SET is_active = 1 WHERE id = ?", (session_id,))
            self.log_audit(conn, session_id, "admin", actor_name, "session_activated", "session", session_id)
            updated = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(updated)

    def update_session(self, session_id: int, fields: dict[str, Any], actor_name: str = "Zapisovateľ") -> dict[str, Any]:
        allowed = {
            "municipality_name",
            "body_name",
            "title",
            "session_number",
            "session_date",
            "chair_name",
            "total_councilors",
            "default_duration_sec",
            "reveal_live_votes",
            "next_resolution_seq",
            "resolution_year",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            s = self.get_session(session_id)
            if not s:
                raise KeyError("Zasadnutie neexistuje.")
            return s
        if "reveal_live_votes" in updates:
            updates["reveal_live_votes"] = 1 if updates["reveal_live_votes"] else 0
        if "total_councilors" in updates and int(updates["total_councilors"]) < 1:
            raise ValueError("Počet poslancov musí byť aspoň 1.")
        if "default_duration_sec" in updates and int(updates["default_duration_sec"]) < 0:
            raise ValueError("Dĺžka odpočtu nemôže byť záporná.")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [session_id]
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                raise KeyError("Zasadnutie neexistuje.")
            conn.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", params)
            self.log_audit(conn, session_id, "admin", actor_name, "session_updated", "session", session_id, updates)
            updated = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(updated)

    # ---------------- Councilors ----------------

    def add_councilor(
        self,
        session_id: int,
        first_name: str,
        last_name: str,
        title: str = "",
        district: str = "",
        pin: str | None = None,
        actor_name: str = "Zapisovateľ",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            sess = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not sess:
                raise KeyError("Zasadnutie neexistuje.")
            existing_pins = {
                r["pin"] for r in conn.execute("SELECT pin FROM councilors WHERE session_id = ?", (session_id,)).fetchall()
            }
            use_pin = pin.strip() if pin and pin.strip() else generate_pin(existing_pins)
            if use_pin in existing_pins:
                raise ValueError(f"PIN {use_pin} už v tomto zasadnutí existuje.")
            token = generate_token()
            cur = conn.execute(
                """
                INSERT INTO councilors (session_id, title, first_name, last_name, district, pin, token, is_present, ever_present, excused, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?)
                """,
                (session_id, title.strip(), first_name.strip(), last_name.strip(), district.strip(), use_pin, token, iso_utc()),
            )
            cid = int(cur.lastrowid)
            self.log_audit(
                conn,
                session_id,
                "admin",
                actor_name,
                "councilor_added",
                "councilor",
                cid,
                {"name": f"{last_name} {first_name}".strip(), "district": district},
            )
            row = conn.execute("SELECT * FROM councilors WHERE id = ?", (cid,)).fetchone()
            return dict(row)

    def delete_councilor(self, councilor_id: int, actor_name: str = "Zapisovateľ") -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM councilors WHERE id = ?", (councilor_id,)).fetchone()
            if not row:
                raise KeyError("Poslanec neexistuje.")
            has_ballots = conn.execute("SELECT 1 FROM vote_ballots WHERE councilor_id = ? LIMIT 1", (councilor_id,)).fetchone()
            if has_ballots:
                raise ValueError("Poslanca, ktorý už má záznamy v hlasovaniach, nie je možné zmazať.")
            conn.execute("DELETE FROM councilors WHERE id = ?", (councilor_id,))
            self.log_audit(
                conn,
                row["session_id"],
                "admin",
                actor_name,
                "councilor_deleted",
                "councilor",
                councilor_id,
                {"name": format_councilor_name(dict(row))},
            )

    def list_councilors(self, session_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = [
                dict(r)
                for r in conn.execute("SELECT * FROM councilors WHERE session_id = ?", (session_id,)).fetchall()
            ]
            rows.sort(key=councilor_sort_key)
            for r in rows:
                r["display_name"] = format_councilor_name(r, last_first=True)
                r["short_name"] = f"{r['last_name']} {r['first_name']}".strip()
            return rows

    def get_councilor(self, councilor_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM councilors WHERE id = ?", (councilor_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["display_name"] = format_councilor_name(d, last_first=True)
            d["short_name"] = f"{d['last_name']} {d['first_name']}".strip()
            return d

    def auth_councilor_by_token(self, token: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM councilors WHERE token = ?", (token.strip(),)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["display_name"] = format_councilor_name(d, last_first=True)
            d["short_name"] = f"{d['last_name']} {d['first_name']}".strip()
            self.log_audit(conn, d["session_id"], "councilor", d["display_name"], "login_qr", "councilor", d["id"])
            return d

    def auth_councilor_by_pin(self, pin: str, session_id: int | None = None) -> dict[str, Any] | None:
        with self.connect() as conn:
            if session_id is None:
                sess = conn.execute("SELECT id FROM sessions WHERE is_active = 1 ORDER BY id DESC LIMIT 1").fetchone()
                if not sess:
                    return None
                session_id = int(sess["id"])
            row = conn.execute(
                "SELECT * FROM councilors WHERE session_id = ? AND pin = ?",
                (session_id, pin.strip()),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["display_name"] = format_councilor_name(d, last_first=True)
            d["short_name"] = f"{d['last_name']} {d['first_name']}".strip()
            self.log_audit(conn, d["session_id"], "councilor", d["display_name"], "login_pin", "councilor", d["id"])
            return d

    def set_councilor_presence(
        self,
        councilor_id: int,
        is_present: bool,
        actor_type: str,
        actor_name: str,
        reason: str = "",
        excused: bool | None = None,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM councilors WHERE id = ?", (councilor_id,)).fetchone()
            if not row:
                raise KeyError("Poslanec neexistuje.")
            session_id = int(row["session_id"])

            open_vote = conn.execute(
                "SELECT * FROM votes WHERE session_id = ? AND status = 'open' LIMIT 1",
                (session_id,),
            ).fetchone()
            if open_vote and actor_type == "councilor":
                raise ValueError("Počas otvoreného hlasovania sa nedá zmeniť prítomnosť v sále (kartička je zamknutá do konca odpočtu).")

            new_present = 1 if is_present else 0
            old_present = int(row["is_present"])
            new_ever = 1 if (row["ever_present"] or new_present) else 0
            new_excused = int(row["excused"]) if excused is None else (1 if excused else 0)
            if new_present:
                new_excused = 0

            conn.execute(
                """
                UPDATE councilors
                SET is_present = ?, ever_present = ?, excused = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_present, new_ever, new_excused, iso_utc(), councilor_id),
            )

            # If admin overrides presence while a vote is open, sync the open vote ballot too
            if open_vote and actor_type == "admin":
                vid = int(open_vote["id"])
                b = conn.execute(
                    "SELECT * FROM vote_ballots WHERE vote_id = ? AND councilor_id = ?",
                    (vid, councilor_id),
                ).fetchone()
                if b:
                    if new_present and not b["was_present"]:
                        conn.execute(
                            "UPDATE vote_ballots SET was_present = 1, choice = 'not_voted', overridden_by_admin = 1, override_reason = ? WHERE id = ?",
                            (reason or "Manuálny príchod počas hlasovania", b["id"]),
                        )
                    elif not new_present and b["was_present"]:
                        conn.execute(
                            "UPDATE vote_ballots SET was_present = 0, choice = 'absent', overridden_by_admin = 1, override_reason = ? WHERE id = ?",
                            (reason or "Manuálny odchod počas hlasovania", b["id"]),
                        )
                self._recompute_vote_counts(conn, vid)

            action = (
                "admin_presence_override"
                if actor_type == "admin"
                else ("presence_in" if new_present else "presence_out")
            )
            self.log_audit(
                conn,
                session_id,
                actor_type,
                actor_name,
                action,
                "councilor",
                councilor_id,
                {
                    "councilor": format_councilor_name(dict(row)),
                    "old_present": bool(old_present),
                    "new_present": bool(new_present),
                    "excused": bool(new_excused),
                    "reason": reason,
                },
            )
            updated = dict(conn.execute("SELECT * FROM councilors WHERE id = ?", (councilor_id,)).fetchone())
            updated["display_name"] = format_councilor_name(updated, last_first=True)
            updated["short_name"] = f"{updated['last_name']} {updated['first_name']}".strip()
            return updated

    # ---------------- Agenda Items ----------------

    def list_agenda_items(self, session_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agenda_items WHERE session_id = ? ORDER BY sort_order ASC, id ASC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_agenda_item(
        self,
        session_id: int,
        item_number: str,
        title: str,
        description: str = "",
        default_quorum: str = "majority_present",
        sort_order: int | None = None,
        actor_name: str = "Zapisovateľ",
    ) -> dict[str, Any]:
        if default_quorum not in VALID_QUORUM_TYPES:
            raise ValueError(f"Neplatné kvórum: {default_quorum}")
        with self.connect() as conn:
            if sort_order is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sort_order), 0) AS mx FROM agenda_items WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                sort_order = int(row["mx"]) + 10
            cur = conn.execute(
                """
                INSERT INTO agenda_items (session_id, item_number, title, description, default_quorum, sort_order, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (session_id, item_number.strip(), title.strip(), description.strip(), default_quorum, int(sort_order), iso_utc()),
            )
            aid = int(cur.lastrowid)
            self.log_audit(
                conn,
                session_id,
                "admin",
                actor_name,
                "agenda_item_added",
                "agenda_item",
                aid,
                {"item_number": item_number.strip(), "title": title.strip(), "default_quorum": default_quorum},
            )
            return dict(conn.execute("SELECT * FROM agenda_items WHERE id = ?", (aid,)).fetchone())

    def update_agenda_item(self, item_id: int, fields: dict[str, Any], actor_name: str = "Zapisovateľ") -> dict[str, Any]:
        allowed = {"item_number", "title", "description", "default_quorum", "sort_order"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "default_quorum" in updates and updates["default_quorum"] not in VALID_QUORUM_TYPES:
            raise ValueError(f"Neplatné kvórum: {updates['default_quorum']}")
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agenda_items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                raise KeyError("Bod programu neexistuje.")
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(f"UPDATE agenda_items SET {set_clause} WHERE id = ?", list(updates.values()) + [item_id])
                self.log_audit(
                    conn,
                    row["session_id"],
                    "admin",
                    actor_name,
                    "agenda_item_updated",
                    "agenda_item",
                    item_id,
                    updates,
                )
            return dict(conn.execute("SELECT * FROM agenda_items WHERE id = ?", (item_id,)).fetchone())

    def delete_agenda_item(self, item_id: int, actor_name: str = "Zapisovateľ") -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agenda_items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                raise KeyError("Bod programu neexistuje.")
            conn.execute("DELETE FROM agenda_items WHERE id = ?", (item_id,))
            self.log_audit(
                conn,
                row["session_id"],
                "admin",
                actor_name,
                "agenda_item_deleted",
                "agenda_item",
                item_id,
                {"item_number": row["item_number"], "title": row["title"]},
            )

    def reorder_agenda_items(self, session_id: int, ordered_ids: list[int], actor_name: str = "Zapisovateľ") -> list[dict[str, Any]]:
        with self.connect() as conn:
            for idx, aid in enumerate(ordered_ids, start=1):
                conn.execute(
                    "UPDATE agenda_items SET sort_order = ? WHERE id = ? AND session_id = ?",
                    (idx * 10, int(aid), session_id),
                )
            self.log_audit(conn, session_id, "admin", actor_name, "agenda_reordered", "session", session_id, {"order": ordered_ids})
            rows = conn.execute(
                "SELECT * FROM agenda_items WHERE session_id = ? ORDER BY sort_order ASC, id ASC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def set_active_agenda_item(self, session_id: int, item_id: int | None, actor_name: str = "Zapisovateľ") -> None:
        with self.connect() as conn:
            conn.execute("UPDATE agenda_items SET is_active = 0 WHERE session_id = ?", (session_id,))
            if item_id is not None:
                row = conn.execute(
                    "SELECT * FROM agenda_items WHERE id = ? AND session_id = ?",
                    (item_id, session_id),
                ).fetchone()
                if not row:
                    raise KeyError("Bod programu neexistuje.")
                conn.execute("UPDATE agenda_items SET is_active = 1 WHERE id = ?", (item_id,))
                self.log_audit(
                    conn,
                    session_id,
                    "admin",
                    actor_name,
                    "agenda_item_activated",
                    "agenda_item",
                    item_id,
                    {"item_number": row["item_number"], "title": row["title"]},
                )

    # ---------------- Votes & Ballots ----------------

    def _recompute_vote_counts(self, conn: sqlite3.Connection, vote_id: int) -> dict[str, Any]:
        vote = dict(conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone())
        ballots = conn.execute("SELECT * FROM vote_ballots WHERE vote_id = ?", (vote_id,)).fetchall()
        counts = {"for": 0, "against": 0, "abstain": 0, "not_voted": 0, "absent": 0}
        present_count = 0
        for b in ballots:
            ch = b["choice"]
            if ch in counts:
                counts[ch] += 1
            if b["was_present"]:
                present_count += 1
        outcome = evaluate_vote(
            vote["quorum_type"],
            int(vote["total_councilors_snapshot"]),
            present_count,
            counts["for"],
        )
        conn.execute(
            """
            UPDATE votes
            SET present_count_snapshot = ?,
                quorum_met = ?,
                required_for = ?,
                for_count = ?,
                against_count = ?,
                abstain_count = ?,
                not_voted_count = ?,
                absent_count = ?,
                passed = ?,
                verdict_sk = ?
            WHERE id = ?
            """,
            (
                present_count,
                1 if outcome.quorum_met else 0,
                outcome.required_for,
                counts["for"],
                counts["against"],
                counts["abstain"],
                counts["not_voted"],
                counts["absent"],
                1 if outcome.passed else 0,
                outcome.verdict_sk,
                vote_id,
            ),
        )
        return dict(conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone())

    def open_vote(
        self,
        session_id: int,
        title: str,
        quorum_type: str = "majority_present",
        duration_sec: int | None = None,
        agenda_item_id: int | None = None,
        item_number_snapshot: str = "",
        repeated_from_vote_id: int | None = None,
        note: str = "",
        actor_name: str = "Zapisovateľ",
    ) -> dict[str, Any]:
        if quorum_type not in VALID_QUORUM_TYPES:
            raise ValueError(f"Neplatný typ kvóra: {quorum_type}")
        with self.connect() as conn:
            sess = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not sess:
                raise KeyError("Zasadnutie neexistuje.")
            already_open = conn.execute(
                "SELECT id, vote_number FROM votes WHERE session_id = ? AND status = 'open' LIMIT 1",
                (session_id,),
            ).fetchone()
            if already_open:
                raise ValueError(f"Hlasovanie č. {already_open['vote_number']} je stále otvorené. Najprv ho uzavrite.")

            councilors = conn.execute("SELECT * FROM councilors WHERE session_id = ?", (session_id,)).fetchall()
            if not councilors:
                raise ValueError("V zasadnutí nie sú pridaní žiadni poslanci.")

            present_count = sum(1 for c in councilors if c["is_present"])
            total_c = int(sess["total_councilors"])
            min_p = min_present_for_quorum(total_c)
            if present_count < min_p:
                raise ValueError(
                    f"Zastupiteľstvo nie je uznášaniaschopné (prítomných {present_count} z {total_c}, potrebných najmenej {min_p})."
                )

            if agenda_item_id is not None:
                item = conn.execute(
                    "SELECT * FROM agenda_items WHERE id = ? AND session_id = ?",
                    (agenda_item_id, session_id),
                ).fetchone()
                if item:
                    if not item_number_snapshot:
                        item_number_snapshot = item["item_number"]
                    conn.execute("UPDATE agenda_items SET is_active = 0 WHERE session_id = ?", (session_id,))
                    conn.execute("UPDATE agenda_items SET is_active = 1 WHERE id = ?", (agenda_item_id,))

            if not item_number_snapshot:
                item_number_snapshot = "—"

            row_mx = conn.execute(
                "SELECT COALESCE(MAX(vote_number), 0) AS mx FROM votes WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            vote_number = int(row_mx["mx"]) + 1

            dur = int(sess["default_duration_sec"]) if duration_sec is None else int(duration_sec)
            if dur < 0:
                raise ValueError("Dĺžka odpočtu nemôže byť záporná.")

            opened = now_utc()
            closes = opened + timedelta(seconds=dur) if dur > 0 else None
            req_for = required_votes_for(quorum_type, total_c, present_count)

            cur = conn.execute(
                """
                INSERT INTO votes (
                    session_id, agenda_item_id, vote_number, item_number_snapshot, title,
                    quorum_type, duration_sec, status, opened_at, closes_at,
                    total_councilors_snapshot, present_count_snapshot, quorum_met, required_for,
                    not_voted_count, absent_count, repeated_from_vote_id, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    agenda_item_id,
                    vote_number,
                    item_number_snapshot.strip(),
                    title.strip(),
                    quorum_type,
                    dur,
                    iso_utc(opened),
                    iso_utc(closes) if closes else None,
                    total_c,
                    present_count,
                    req_for,
                    present_count,
                    len(councilors) - present_count,
                    repeated_from_vote_id,
                    note.strip(),
                ),
            )
            vid = int(cur.lastrowid)

            for c in councilors:
                was_p = 1 if c["is_present"] else 0
                conn.execute(
                    """
                    INSERT INTO vote_ballots (vote_id, councilor_id, was_present, choice)
                    VALUES (?, ?, ?, ?)
                    """,
                    (vid, c["id"], was_p, "not_voted" if was_p else "absent"),
                )

            self.log_audit(
                conn,
                session_id,
                "admin",
                actor_name,
                "vote_opened",
                "vote",
                vid,
                {
                    "vote_number": vote_number,
                    "item_number": item_number_snapshot,
                    "title": title.strip(),
                    "quorum_type": quorum_type,
                    "duration_sec": dur,
                    "present_count": present_count,
                    "total_councilors": total_c,
                    "repeated_from_vote_id": repeated_from_vote_id,
                },
            )
            return dict(conn.execute("SELECT * FROM votes WHERE id = ?", (vid,)).fetchone())

    def extend_vote(self, vote_id: int, add_seconds: int = 10, actor_name: str = "Zapisovateľ") -> dict[str, Any]:
        if add_seconds < 1:
            raise ValueError("Predĺženie musí byť aspoň 1 sekunda.")
        with self.connect() as conn:
            vote = conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone()
            if not vote:
                raise KeyError("Hlasovanie neexistuje.")
            if vote["status"] != "open":
                raise ValueError("Uzavreté hlasovanie nie je možné predĺžiť.")
            base_dt = parse_iso(vote["closes_at"]) or now_utc()
            now_dt = now_utc()
            new_closes = max(base_dt, now_dt) + timedelta(seconds=add_seconds)
            new_dur = int(vote["duration_sec"]) + add_seconds
            conn.execute(
                "UPDATE votes SET closes_at = ?, duration_sec = ? WHERE id = ?",
                (iso_utc(new_closes), new_dur, vote_id),
            )
            self.log_audit(
                conn,
                vote["session_id"],
                "admin",
                actor_name,
                "vote_extended",
                "vote",
                vote_id,
                {"vote_number": vote["vote_number"], "add_seconds": add_seconds, "new_closes_at": iso_utc(new_closes)},
            )
            return dict(conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone())

    def cast_ballot(self, vote_id: int, councilor_id: int, choice: str) -> dict[str, Any]:
        if choice not in VALID_VOTE_CHOICES:
            raise ValueError(f"Neplatná voľba hlasu: {choice}")
        with self.connect() as conn:
            vote = conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone()
            if not vote:
                raise KeyError("Hlasovanie neexistuje.")
            if vote["status"] != "open":
                raise ValueError("Hlasovanie je už uzavreté.")
            ballot = conn.execute(
                "SELECT * FROM vote_ballots WHERE vote_id = ? AND councilor_id = ?",
                (vote_id, councilor_id),
            ).fetchone()
            if not ballot:
                raise KeyError("Poslanec nie je súčasťou tohto zasadnutia.")
            if not ballot["was_present"]:
                raise ValueError("Nie ste prihlásený v sále (kartička nie je zasunutá), nemôžete hlasovať.")

            councilor = dict(conn.execute("SELECT * FROM councilors WHERE id = ?", (councilor_id,)).fetchone())
            old_choice = ballot["choice"]
            action = "vote_cast" if old_choice == "not_voted" else "vote_changed"
            conn.execute(
                "UPDATE vote_ballots SET choice = ?, cast_at = ? WHERE id = ?",
                (choice, iso_utc(), ballot["id"]),
            )
            self._recompute_vote_counts(conn, vote_id)
            self.log_audit(
                conn,
                vote["session_id"],
                "councilor",
                format_councilor_name(councilor),
                action,
                "vote",
                vote_id,
                {
                    "vote_number": vote["vote_number"],
                    "old_choice": old_choice,
                    "new_choice": choice,
                },
            )
            return dict(conn.execute("SELECT * FROM vote_ballots WHERE id = ?", (ballot["id"],)).fetchone())

    def close_vote(
        self,
        vote_id: int,
        actor_type: str = "admin",
        actor_name: str = "Zapisovateľ",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            vote = conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone()
            if not vote:
                raise KeyError("Hlasovanie neexistuje.")
            if vote["status"] == "closed":
                return dict(vote)

            conn.execute(
                "UPDATE votes SET status = 'closed', closed_at = ? WHERE id = ?",
                (iso_utc(), vote_id),
            )
            updated = self._recompute_vote_counts(conn, vote_id)
            self.log_audit(
                conn,
                vote["session_id"],
                actor_type,
                actor_name,
                "vote_closed",
                "vote",
                vote_id,
                {
                    "vote_number": updated["vote_number"],
                    "verdict": updated["verdict_sk"],
                    "for": updated["for_count"],
                    "against": updated["against_count"],
                    "abstain": updated["abstain_count"],
                    "not_voted": updated["not_voted_count"],
                    "present": updated["present_count_snapshot"],
                    "required_for": updated["required_for"],
                },
            )
            return updated

    def admin_override_ballot(
        self,
        vote_id: int,
        councilor_id: int,
        new_choice: str,
        reason: str,
        actor_name: str = "Zapisovateľ",
    ) -> dict[str, Any]:
        if new_choice not in VALID_BALLOT_STATES:
            raise ValueError(f"Neplatný stav hlasu: {new_choice}")
        if not reason or not reason.strip():
            raise ValueError("Pri manuálnom zásahu zapisovateľa je dôvod povinný.")
        with self.connect() as conn:
            vote = conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone()
            if not vote:
                raise KeyError("Hlasovanie neexistuje.")
            ballot = conn.execute(
                "SELECT * FROM vote_ballots WHERE vote_id = ? AND councilor_id = ?",
                (vote_id, councilor_id),
            ).fetchone()
            if not ballot:
                raise KeyError("Záznam hlasovania poslanca neexistuje.")
            councilor = dict(conn.execute("SELECT * FROM councilors WHERE id = ?", (councilor_id,)).fetchone())
            old_choice = ballot["choice"]
            old_present = int(ballot["was_present"])
            new_present = 0 if new_choice == "absent" else 1
            conn.execute(
                """
                UPDATE vote_ballots
                SET was_present = ?, choice = ?, cast_at = ?, overridden_by_admin = 1, override_reason = ?
                WHERE id = ?
                """,
                (new_present, new_choice, iso_utc(), reason.strip(), ballot["id"]),
            )
            updated_vote = self._recompute_vote_counts(conn, vote_id)
            self.log_audit(
                conn,
                vote["session_id"],
                "admin",
                actor_name,
                "admin_vote_override",
                "vote",
                vote_id,
                {
                    "vote_number": vote["vote_number"],
                    "councilor": format_councilor_name(councilor),
                    "old_choice": old_choice,
                    "new_choice": new_choice,
                    "old_present": bool(old_present),
                    "new_present": bool(new_present),
                    "reason": reason.strip(),
                    "recalculated_verdict": updated_vote["verdict_sk"],
                },
            )
            return updated_vote

    def assign_resolution_number(
        self,
        vote_id: int,
        resolution_number: str | None,
        auto_next: bool = False,
        actor_name: str = "Zapisovateľ",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            vote = conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone()
            if not vote:
                raise KeyError("Hlasovanie neexistuje.")
            sess = conn.execute("SELECT * FROM sessions WHERE id = ?", (vote["session_id"],)).fetchone()
            if auto_next:
                seq = int(sess["next_resolution_seq"])
                year = int(sess["resolution_year"])
                res_num = f"{seq}/{year}"
                conn.execute(
                    "UPDATE sessions SET next_resolution_seq = ? WHERE id = ?",
                    (seq + 1, sess["id"]),
                )
            else:
                res_num = resolution_number.strip() if resolution_number and resolution_number.strip() else None

            conn.execute("UPDATE votes SET resolution_number = ? WHERE id = ?", (res_num, vote_id))
            self.log_audit(
                conn,
                vote["session_id"],
                "admin",
                actor_name,
                "resolution_assigned",
                "vote",
                vote_id,
                {"vote_number": vote["vote_number"], "resolution_number": res_num},
            )
            return dict(conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone())

    def get_vote_with_ballots(self, vote_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone()
            if not row:
                return None
            vote = dict(row)
            ballot_rows = conn.execute(
                """
                SELECT b.*, c.title, c.first_name, c.last_name, c.district
                FROM vote_ballots b
                JOIN councilors c ON c.id = b.councilor_id
                WHERE b.vote_id = ?
                """,
                (vote_id,),
            ).fetchall()
            ballots = [dict(b) for b in ballot_rows]
            ballots.sort(key=councilor_sort_key)
            for b in ballots:
                b["display_name"] = format_councilor_name(b, last_first=True)
                b["short_name"] = f"{b['last_name']} {b['first_name']}".strip()
                b["has_voted"] = b["choice"] in VALID_VOTE_CHOICES
            vote["ballots"] = ballots
            vote["quorum_label"] = QUORUM_LABELS[vote["quorum_type"]]["label"]
            vote["quorum_short"] = QUORUM_LABELS[vote["quorum_type"]]["short"]
            return vote

    def list_votes(self, session_id: int, include_ballots: bool = True) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM votes WHERE session_id = ? ORDER BY vote_number ASC",
                (session_id,),
            ).fetchall()
        votes: list[dict[str, Any]] = []
        for r in rows:
            if include_ballots:
                v = self.get_vote_with_ballots(int(r["id"]))
                if v:
                    votes.append(v)
            else:
                with self.connect() as conn:
                    v = dict(conn.execute("SELECT * FROM votes WHERE id = ?", (r["id"],)).fetchone())
                    v["quorum_label"] = QUORUM_LABELS[v["quorum_type"]]["label"]
                    votes.append(v)
        return votes

    def list_audit_logs(self, session_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if session_id is not None:
                rows = conn.execute(
                    "SELECT * FROM audit_logs WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["details"] = json.loads(d["details_json"])
                except Exception:
                    d["details"] = {}
                result.append(d)
            return result

    # ---------------- Real-time State Payloads ----------------

    def _remaining_seconds(self, vote: dict[str, Any]) -> float | None:
        if vote["status"] != "open" or not vote.get("closes_at"):
            return None
        closes = parse_iso(vote["closes_at"])
        if not closes:
            return None
        return max(0.0, (closes - now_utc()).total_seconds())

    def _mask_vote_for_public(self, vote: dict[str, Any], reveal_live: bool) -> dict[str, Any]:
        """Hide individual choices while vote is open unless reveal_live is enabled."""
        out = dict(vote)
        out["remaining_sec"] = self._remaining_seconds(vote)
        if vote["status"] == "open" and not reveal_live:
            out["for_count"] = None
            out["against_count"] = None
            out["abstain_count"] = None
            out["verdict_sk"] = ""
            out["passed"] = None
            voted_count = sum(1 for b in vote["ballots"] if b["has_voted"])
            out["voted_count"] = voted_count
            masked_ballots = []
            for b in vote["ballots"]:
                mb = {
                    "councilor_id": b["councilor_id"],
                    "display_name": b["display_name"],
                    "short_name": b["short_name"],
                    "district": b["district"],
                    "was_present": bool(b["was_present"]),
                    "has_voted": b["has_voted"],
                    "choice": None,
                    "overridden_by_admin": bool(b["overridden_by_admin"]),
                }
                masked_ballots.append(mb)
            out["ballots"] = masked_ballots
        else:
            out["voted_count"] = sum(1 for b in vote["ballots"] if b["has_voted"])
        return out

    def build_public_state(self, session_id: int | None = None, for_admin: bool = False) -> dict[str, Any]:
        sess = self.get_session(session_id) if session_id is not None else self.get_active_session()
        if not sess:
            return {"session": None, "server_time": iso_utc()}

        sid = int(sess["id"])
        councilors = self.list_councilors(sid)
        agenda = self.list_agenda_items(sid)
        active_item = next((a for a in agenda if a["is_active"]), None)

        present_count = sum(1 for c in councilors if c["is_present"])
        total_c = int(sess["total_councilors"])
        min_p = min_present_for_quorum(total_c)
        quorate = is_quorate(total_c, present_count)

        with self.connect() as conn:
            open_row = conn.execute(
                "SELECT id FROM votes WHERE session_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
                (sid,),
            ).fetchone()
            latest_closed_row = conn.execute(
                "SELECT id FROM votes WHERE session_id = ? AND status = 'closed' ORDER BY vote_number DESC LIMIT 1",
                (sid,),
            ).fetchone()

        reveal_live = bool(sess["reveal_live_votes"])
        current_vote = None
        if open_row:
            v = self.get_vote_with_ballots(int(open_row["id"]))
            if v:
                current_vote = v if for_admin else self._mask_vote_for_public(v, reveal_live)
                current_vote["remaining_sec"] = self._remaining_seconds(v)

        last_closed_vote = None
        if latest_closed_row:
            v = self.get_vote_with_ballots(int(latest_closed_row["id"]))
            if v:
                last_closed_vote = v
                last_closed_vote["voted_count"] = sum(1 for b in v["ballots"] if b["has_voted"])

        # Strip sensitive PIN/token for non-admin clients
        public_councilors = []
        for c in councilors:
            item = {
                "id": c["id"],
                "title": c["title"],
                "first_name": c["first_name"],
                "last_name": c["last_name"],
                "display_name": c["display_name"],
                "short_name": c["short_name"],
                "district": c["district"],
                "is_present": bool(c["is_present"]),
                "ever_present": bool(c["ever_present"]),
                "excused": bool(c["excused"]),
            }
            if for_admin:
                item["pin"] = c["pin"]
                item["token"] = c["token"]
            public_councilors.append(item)

        payload: dict[str, Any] = {
            "server_time": iso_utc(),
            "session": sess,
            "attendance": {
                "present_count": present_count,
                "total_councilors": total_c,
                "min_present": min_p,
                "quorate": quorate,
            },
            "councilors": public_councilors,
            "agenda": agenda,
            "active_agenda_item": active_item,
            "current_vote": current_vote,
            "last_closed_vote": last_closed_vote,
            "quorum_types": QUORUM_LABELS,
        }
        if for_admin:
            payload["votes"] = self.list_votes(sid, include_ballots=True)
        return payload

    def build_councilor_state(self, councilor_id: int) -> dict[str, Any] | None:
        c = self.get_councilor(councilor_id)
        if not c:
            return None
        state = self.build_public_state(session_id=int(c["session_id"]), for_admin=False)
        my_ballot = None
        if state.get("current_vote"):
            with self.connect() as conn:
                b = conn.execute(
                    "SELECT * FROM vote_ballots WHERE vote_id = ? AND councilor_id = ?",
                    (state["current_vote"]["id"], councilor_id),
                ).fetchone()
                if b:
                    my_ballot = dict(b)
        state["me"] = {
            "id": c["id"],
            "display_name": c["display_name"],
            "short_name": c["short_name"],
            "district": c["district"],
            "is_present": bool(c["is_present"]),
        }
        state["my_ballot"] = my_ballot
        return state

    # ---------------- Demo Seed ----------------

    def seed_demo_if_empty(self) -> dict[str, Any] | None:
        """Create an anonymized 13-councilor demo session if DB has no sessions."""
        if self.list_sessions():
            return self.get_active_session()

        today = datetime.now().strftime("%Y-%m-%d")
        sess = self.create_session(
            title="Demo zasadnutie MiZ (testovacie dáta)",
            session_date=today,
            municipality_name="MČ Košice – Dargovských hrdinov (DEMO)",
            body_name="Miestne zastupiteľstvo",
            session_number="1",
            chair_name="Predsedajúci (Demo)",
            total_councilors=13,
            default_duration_sec=15,
            reveal_live_votes=False,
            next_resolution_seq=1,
            resolution_year=int(today[:4]),
            activate=True,
            actor_name="Systém (seed)",
        )
        sid = int(sess["id"])

        demo_councilors = [
            ("Ing.", "Martin", "Bielik", "Obvod 1", "1001"),
            ("Mgr.", "Zuzana", "Černá", "Obvod 1", "1002"),
            ("", "Peter", "Dvořák", "Obvod 1", "1003"),
            ("JUDr.", "Elena", "Farkašová", "Obvod 2", "1004"),
            ("Ing.", "Tomáš", "Gál", "Obvod 2", "1005"),
            ("Mgr.", "Lucia", "Horváthová", "Obvod 2", "1006"),
            ("", "Marek", "Kováč", "Obvod 2", "1007"),
            ("MUDr.", "Jana", "Lukáčová", "Obvod 2", "1008"),
            ("Ing.", "Róbert", "Molnár", "Obvod 3", "1009"),
            ("Mgr.", "Katarína", "Nováková", "Obvod 3", "1010"),
            ("", "Štefan", "Oravec", "Obvod 3", "1011"),
            ("Ing.", "Andrea", "Poláková", "Obvod 3", "1012"),
            ("PhDr.", "Vladimír", "Varga", "Obvod 3", "1013"),
        ]
        created_ids = []
        for title, fn, ln, dist, pin in demo_councilors:
            c = self.add_councilor(sid, fn, ln, title=title, district=dist, pin=pin, actor_name="Systém (seed)")
            created_ids.append(int(c["id"]))

        # Mark first 10 councilors present so demo is immediately quorate (10/13)
        for cid in created_ids[:10]:
            self.set_councilor_presence(cid, True, "admin", "Systém (seed)", "Demo prezenčka")

        demo_agenda = [
            ("1", "Otvorenie a schválenie programu zasadnutia", "majority_present"),
            ("1.1", "Návrh na doplnenie programu zasadnutia (§ 12 ods. 5)", "majority_all"),
            ("2", "Voľba návrhovej komisie a overovateľov zápisnice", "majority_present"),
            ("3", "Zmena rozpočtu mestskej časti na rok 2026", "majority_present"),
            ("4", "Návrh VZN o podmienkach správy verejnej zelene (VZN = 3/5 prítomných)", "three_fifths_present"),
            ("5", "Prenájom pozemku z dôvodu hodného osobitného zreteľa (3/5 všetkých)", "three_fifths_all"),
            ("6", "Interpelácie a diskusia (bez uznesenia)", "majority_present"),
        ]
        first_item_id = None
        for idx, (num, title, q) in enumerate(demo_agenda, start=1):
            it = self.add_agenda_item(sid, num, title, default_quorum=q, sort_order=idx * 10, actor_name="Systém (seed)")
            if first_item_id is None:
                first_item_id = int(it["id"])
        if first_item_id is not None:
            self.set_active_agenda_item(sid, first_item_id, actor_name="Systém (seed)")

        return self.get_session(sid)
