"""SQLite FTS5 transcript index for JSONL session transcripts."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class TranscriptIndex:
    """Full-text search index over transcript JSONL files."""

    def __init__(self, db_path: str = "data/transcript_index.db") -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> None:
        """Create SQLite tables, triggers, and the FTS index if needed."""
        with self._lock:
            if self._initialized:
                return

            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS transcript_entries (
                        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        entry_type TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TEXT,
                        entry_hash TEXT NOT NULL UNIQUE
                    );

                    CREATE TABLE IF NOT EXISTS session_progress (
                        session_id TEXT PRIMARY KEY,
                        last_line INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(
                        session_id,
                        entry_type,
                        content,
                        timestamp UNINDEXED,
                        content='transcript_entries',
                        content_rowid='entry_id'
                    );

                    CREATE TRIGGER IF NOT EXISTS transcript_entries_ai
                    AFTER INSERT ON transcript_entries
                    BEGIN
                        INSERT INTO transcript_fts(rowid, session_id, entry_type, content, timestamp)
                        VALUES (new.entry_id, new.session_id, new.entry_type, new.content, new.timestamp);
                    END;

                    CREATE TRIGGER IF NOT EXISTS transcript_entries_ad
                    AFTER DELETE ON transcript_entries
                    BEGIN
                        INSERT INTO transcript_fts(transcript_fts, rowid, session_id, entry_type, content, timestamp)
                        VALUES ('delete', old.entry_id, old.session_id, old.entry_type, old.content, old.timestamp);
                    END;

                    CREATE TRIGGER IF NOT EXISTS transcript_entries_au
                    AFTER UPDATE ON transcript_entries
                    BEGIN
                        INSERT INTO transcript_fts(transcript_fts, rowid, session_id, entry_type, content, timestamp)
                        VALUES ('delete', old.entry_id, old.session_id, old.entry_type, old.content, old.timestamp);
                        INSERT INTO transcript_fts(rowid, session_id, entry_type, content, timestamp)
                        VALUES (new.entry_id, new.session_id, new.entry_type, new.content, new.timestamp);
                    END;
                    """
                )
            self._initialized = True

    def append_entry(self, session_id: str, entry: dict) -> None:
        """Index a single transcript entry immediately after JSONL append."""
        self.initialize()
        with self._lock, self._connect() as conn:
            normalized = self._normalize_entry(session_id, entry)
            if normalized is not None:
                self._insert_entry(conn, normalized)
            self._increment_progress(conn, session_id)

    def index_session(self, session_id: str, jsonl_path: Path) -> int:
        """Index new lines from one JSONL transcript file."""
        self.initialize()
        if not jsonl_path.exists():
            return 0

        with self._lock, self._connect() as conn:
            last_line = self._get_progress(conn, session_id)
            indexed = 0
            processed_line = last_line

            for line_number, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
                if line_number <= last_line:
                    continue

                processed_line = line_number
                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    logger.warning("TranscriptIndex: skipping malformed line in %s: %s", jsonl_path, exc)
                    continue

                normalized = self._normalize_entry(session_id, entry)
                if normalized is None:
                    continue

                indexed += self._insert_entry(conn, normalized)

            if processed_line > last_line:
                self._set_progress(conn, session_id, processed_line)

            return indexed

    def index_all(self, transcripts_dir: Path) -> int:
        """Bulk-index all transcript JSONL files in a directory."""
        self.initialize()
        if not transcripts_dir.exists():
            return 0

        total_indexed = 0
        for jsonl_path in sorted(transcripts_dir.glob("*.jsonl")):
            total_indexed += self.index_session(jsonl_path.stem, jsonl_path)
        return total_indexed

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search transcripts using an FTS5 MATCH query."""
        self.initialize()
        text = query.strip()
        if not text or limit <= 0:
            return []

        with self._lock, self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT
                        transcript_entries.session_id AS session_id,
                        transcript_entries.entry_type AS entry_type,
                        transcript_entries.content AS content,
                        transcript_entries.timestamp AS timestamp,
                        bm25(transcript_fts) AS score
                    FROM transcript_fts
                    JOIN transcript_entries ON transcript_entries.entry_id = transcript_fts.rowid
                    WHERE transcript_fts MATCH ?
                    ORDER BY score ASC, transcript_entries.entry_id DESC
                    LIMIT ?
                    """,
                    (text, limit),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                logger.warning("TranscriptIndex: invalid search query %r: %s", query, exc)
                return []

        return [
            {
                "session_id": row["session_id"],
                "entry_type": row["entry_type"],
                "content": row["content"],
                "timestamp": row["timestamp"],
                "score": float(row["score"]),
            }
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _normalize_entry(self, session_id: str, entry: dict) -> dict | None:
        entry_type = str(entry.get("type", "")).strip()
        timestamp = entry.get("ts")

        searchable_text = self._build_searchable_text(entry_type, entry)
        if not searchable_text:
            return None

        canonical_entry = json.dumps(entry, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        entry_hash = hashlib.sha256(f"{session_id}:{canonical_entry}".encode("utf-8")).hexdigest()
        return {
            "session_id": session_id,
            "entry_type": entry_type,
            "content": searchable_text,
            "timestamp": timestamp,
            "entry_hash": entry_hash,
        }

    def _build_searchable_text(self, entry_type: str, entry: dict) -> str:
        if entry_type in {"user", "assistant", "tool_result"}:
            text = str(entry.get("content", "")).strip()
            return " ".join(text.split())

        if entry_type == "tool_call":
            name = str(entry.get("name", "")).strip()
            arguments = entry.get("arguments", {})
            if isinstance(arguments, str):
                args_text = arguments
            else:
                args_text = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            combined = f"{name} {args_text}".strip()
            return " ".join(combined.split())

        return ""

    def _insert_entry(self, conn: sqlite3.Connection, entry: dict) -> int:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO transcript_entries (
                session_id,
                entry_type,
                content,
                timestamp,
                entry_hash
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                entry["session_id"],
                entry["entry_type"],
                entry["content"],
                entry["timestamp"],
                entry["entry_hash"],
            ),
        )
        return int(cursor.rowcount or 0)

    def _get_progress(self, conn: sqlite3.Connection, session_id: str) -> int:
        row = conn.execute(
            "SELECT last_line FROM session_progress WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return 0
        return int(row["last_line"])

    def _increment_progress(self, conn: sqlite3.Connection, session_id: str) -> None:
        conn.execute(
            """
            INSERT INTO session_progress (session_id, last_line)
            VALUES (?, 1)
            ON CONFLICT(session_id) DO UPDATE
            SET last_line = session_progress.last_line + 1
            """,
            (session_id,),
        )

    def _set_progress(self, conn: sqlite3.Connection, session_id: str, last_line: int) -> None:
        conn.execute(
            """
            INSERT INTO session_progress (session_id, last_line)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE
            SET last_line = CASE
                WHEN excluded.last_line > session_progress.last_line THEN excluded.last_line
                ELSE session_progress.last_line
            END
            """,
            (session_id, last_line),
        )
