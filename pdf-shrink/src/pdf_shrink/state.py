"""SQLiteによる処理結果の永続化と再開判定。"""
from __future__ import annotations

import datetime
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from . import discovery
from .models import CandidateResult, ProcessResult, ProcessStatus, SourceSnapshot
from .utils import sha256_file

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    source_path       TEXT PRIMARY KEY,
    source_sha256     TEXT NOT NULL,
    source_size       INTEGER NOT NULL,
    source_mtime_ns   INTEGER NOT NULL,
    config_hash       TEXT NOT NULL,
    mode              TEXT,
    status            TEXT NOT NULL,
    output_size       INTEGER,
    output_sha256     TEXT,
    saved_bytes       INTEGER,
    saved_percent     REAL,
    page_count        INTEGER,
    scan_page_ratio   REAL,
    error_message     TEXT,
    pymupdf_version   TEXT,
    qpdf_version      TEXT,
    processed_at      TEXT,
    profile           TEXT NOT NULL DEFAULT '',
    decision_reason   TEXT NOT NULL DEFAULT '',
    candidate_size    INTEGER,
    candidate_saved_bytes INTEGER,
    candidate_saved_percent REAL,
    images_changed    INTEGER NOT NULL DEFAULT 0,
    candidate_details TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_sha256 ON files(source_sha256);
"""

TERMINAL_STATUSES = frozenset(status.value for status in ProcessStatus)

# Adding nullable sizes preserves the distinction between no candidate and a
# candidate that saved zero bytes.  Legacy rows have no recorded diagnostics.
DIAGNOSTIC_COLUMNS = {
    "profile": "TEXT NOT NULL DEFAULT ''",
    "decision_reason": "TEXT NOT NULL DEFAULT ''",
    "candidate_size": "INTEGER",
    "candidate_saved_bytes": "INTEGER",
    "candidate_saved_percent": "REAL",
    "images_changed": "INTEGER NOT NULL DEFAULT 0",
    "candidate_details": "TEXT NOT NULL DEFAULT '[]'",
}


@dataclass(frozen=True)
class Record:
    source_path: str
    source_sha256: str
    source_size: int
    source_mtime_ns: int
    config_hash: str
    mode: str | None
    status: str
    output_size: int | None
    output_sha256: str | None
    saved_bytes: int | None
    saved_percent: float | None
    page_count: int | None
    scan_page_ratio: float | None
    error_message: str | None
    pymupdf_version: str | None
    qpdf_version: str | None
    processed_at: str | None
    profile: str = ""
    decision_reason: str = ""
    candidate_size: int | None = None
    candidate_saved_bytes: int | None = None
    candidate_saved_percent: float | None = None
    images_changed: int = 0
    candidate_details: tuple[CandidateResult, ...] = ()


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.executescript(SCHEMA)
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(files)").fetchall()
    }
    if "output_sha256" not in columns:
        # Existing databases predate output-content verification.  NULL makes
        # every legacy terminal row run once, after which save_result stores a
        # digest that can be checked on subsequent runs.
        conn.execute("ALTER TABLE files ADD COLUMN output_sha256 TEXT")
    for name, declaration in DIAGNOSTIC_COLUMNS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE files ADD COLUMN {name} {declaration}")
    conn.commit()
    return conn


def candidate_details_json(details: tuple[CandidateResult, ...]) -> str:
    """Use the same JSON representation in state and CSV diagnostics."""
    return json.dumps(
        [asdict(candidate) for candidate in details],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _record_from_row(row: sqlite3.Row) -> Record:
    return Record(
        source_path=row["source_path"],
        source_sha256=row["source_sha256"],
        source_size=row["source_size"],
        source_mtime_ns=row["source_mtime_ns"],
        config_hash=row["config_hash"],
        mode=row["mode"],
        status=row["status"],
        output_size=row["output_size"],
        output_sha256=row["output_sha256"],
        saved_bytes=row["saved_bytes"],
        saved_percent=row["saved_percent"],
        page_count=row["page_count"],
        scan_page_ratio=row["scan_page_ratio"],
        error_message=row["error_message"],
        pymupdf_version=row["pymupdf_version"],
        qpdf_version=row["qpdf_version"],
        processed_at=row["processed_at"],
        profile=row["profile"],
        decision_reason=row["decision_reason"],
        candidate_size=row["candidate_size"],
        candidate_saved_bytes=row["candidate_saved_bytes"],
        candidate_saved_percent=row["candidate_saved_percent"],
        images_changed=row["images_changed"],
        candidate_details=tuple(
            CandidateResult(**candidate)
            for candidate in json.loads(row["candidate_details"])
        ),
    )


def _fetch_records(
    conn: sqlite3.Connection,
    query: str,
    parameters: tuple[str, ...] = (),
) -> list[Record]:
    previous_factory = conn.row_factory
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, parameters).fetchall()
        return [_record_from_row(row) for row in rows]
    finally:
        conn.row_factory = previous_factory


def get_record(conn: sqlite3.Connection, source_path: str) -> Record | None:
    records = _fetch_records(
        conn,
        "SELECT * FROM files WHERE source_path = ?",
        (source_path,),
    )
    return records[0] if records else None


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def should_process(
    record: Record | None,
    sha256: str,
    config_hash: str,
    retry_errors: bool,
    output_matches_record: bool,
    *,
    output_required: bool = True,
) -> bool:
    if record is None:
        return True
    if record.source_sha256 != sha256:
        return True
    if record.config_hash != config_hash:
        return True
    if output_required and is_terminal(record.status) and not record.output_sha256:
        return True
    if record.status == ProcessStatus.ERROR:
        # 復旧コピーにも失敗したERRORは、出力を回復するため自動再試行する。
        if record.output_size is None or (output_required and not output_matches_record):
            return True
        return retry_errors
    if output_required and is_terminal(record.status) and not output_matches_record:
        return True
    return not is_terminal(record.status)


def save_result(
    conn: sqlite3.Connection,
    source: SourceSnapshot,
    result: ProcessResult,
    config_hash: str,
    *,
    input_dir: Path,
    pymupdf_version: str,
    qpdf_version: str,
    commit: bool = True,
) -> None:
    processed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    output_sha256 = _stable_output_sha256(result)
    if result.output_size is not None and output_sha256 is None:
        raise OSError(
            f"Could not capture a stable PDF output digest: {result.output_path}"
        )
    # Hashing a large output creates another race window.  Reconfirm the input
    # after that work and immediately before writing the completion record.
    discovery.assert_source_unchanged(source, input_dir)
    conn.execute(
        """
        INSERT INTO files (
            source_path, source_sha256, source_size, source_mtime_ns, config_hash,
            mode, status, output_size, output_sha256, saved_bytes, saved_percent,
            error_message,
            pymupdf_version, qpdf_version, page_count, scan_page_ratio, processed_at,
            profile, decision_reason, candidate_size, candidate_saved_bytes,
            candidate_saved_percent, images_changed, candidate_details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_path) DO UPDATE SET
            source_sha256 = excluded.source_sha256,
            source_size = excluded.source_size,
            source_mtime_ns = excluded.source_mtime_ns,
            config_hash = excluded.config_hash,
            mode = excluded.mode,
            status = excluded.status,
            output_size = excluded.output_size,
            output_sha256 = excluded.output_sha256,
            saved_bytes = excluded.saved_bytes,
            saved_percent = excluded.saved_percent,
            error_message = excluded.error_message,
            pymupdf_version = excluded.pymupdf_version,
            qpdf_version = excluded.qpdf_version,
            page_count = excluded.page_count,
            scan_page_ratio = excluded.scan_page_ratio,
            processed_at = excluded.processed_at,
            profile = excluded.profile,
            decision_reason = excluded.decision_reason,
            candidate_size = excluded.candidate_size,
            candidate_saved_bytes = excluded.candidate_saved_bytes,
            candidate_saved_percent = excluded.candidate_saved_percent,
            images_changed = excluded.images_changed,
            candidate_details = excluded.candidate_details
        """,
        (
            str(source.path),
            source.sha256,
            source.size,
            source.mtime_ns,
            config_hash,
            str(result.mode) if result.mode else None,
            str(result.status),
            result.output_size,
            output_sha256,
            result.saved_bytes,
            result.saved_percent,
            result.error_message,
            pymupdf_version,
            qpdf_version,
            result.page_count,
            result.scan_page_ratio,
            processed_at,
            result.profile,
            result.decision_reason,
            result.candidate_size,
            result.candidate_saved_bytes,
            result.candidate_saved_percent,
            result.images_changed,
            candidate_details_json(result.candidate_details),
        ),
    )
    if commit:
        conn.commit()


def _stable_output_sha256(result: ProcessResult) -> str | None:
    """Hash a published output only when it still matches the result snapshot."""
    if result.output_size is None:
        return None
    try:
        before = result.output_path.stat()
        if not result.output_path.is_file() or before.st_size != result.output_size:
            return None
        digest = sha256_file(result.output_path)
        after = result.output_path.stat()
    except OSError:
        return None
    before_signature = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_signature = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    return digest if before_signature == after_signature else None


def list_records(conn: sqlite3.Connection) -> list[Record]:
    return _fetch_records(conn, "SELECT * FROM files ORDER BY source_path")


def list_records_for_paths(
    conn: sqlite3.Connection,
    source_paths: Iterable[str],
) -> list[Record]:
    """現在の入力集合だけを返す。SQLiteの変数上限を避けて分割照会する。"""
    paths = sorted(set(source_paths))
    records: list[Record] = []
    chunk_size = 900
    for start in range(0, len(paths), chunk_size):
        chunk = paths[start:start + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        records.extend(
            _fetch_records(
                conn,
                f"SELECT * FROM files WHERE source_path IN ({placeholders})",
                tuple(chunk),
            )
        )
    return sorted(records, key=lambda record: record.source_path)
