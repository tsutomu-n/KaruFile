"""SQLiteによる処理結果の永続化と再開判定。"""
from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import ProcessResult, ProcessStatus, SourceSnapshot

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
    saved_bytes       INTEGER,
    saved_percent     REAL,
    page_count        INTEGER,
    scan_page_ratio   REAL,
    error_message     TEXT,
    pymupdf_version   TEXT,
    qpdf_version      TEXT,
    processed_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_sha256 ON files(source_sha256);
"""

TERMINAL_STATUSES = frozenset(status.value for status in ProcessStatus)


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
    saved_bytes: int | None
    saved_percent: float | None
    page_count: int | None
    scan_page_ratio: float | None
    error_message: str | None
    pymupdf_version: str | None
    qpdf_version: str | None
    processed_at: str | None


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


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
        saved_bytes=row["saved_bytes"],
        saved_percent=row["saved_percent"],
        page_count=row["page_count"],
        scan_page_ratio=row["scan_page_ratio"],
        error_message=row["error_message"],
        pymupdf_version=row["pymupdf_version"],
        qpdf_version=row["qpdf_version"],
        processed_at=row["processed_at"],
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
    pymupdf_version: str,
    qpdf_version: str,
) -> None:
    processed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO files (
            source_path, source_sha256, source_size, source_mtime_ns, config_hash,
            mode, status, output_size, saved_bytes, saved_percent, error_message,
            pymupdf_version, qpdf_version, page_count, scan_page_ratio, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_path) DO UPDATE SET
            source_sha256 = excluded.source_sha256,
            source_size = excluded.source_size,
            source_mtime_ns = excluded.source_mtime_ns,
            config_hash = excluded.config_hash,
            mode = excluded.mode,
            status = excluded.status,
            output_size = excluded.output_size,
            saved_bytes = excluded.saved_bytes,
            saved_percent = excluded.saved_percent,
            error_message = excluded.error_message,
            pymupdf_version = excluded.pymupdf_version,
            qpdf_version = excluded.qpdf_version,
            page_count = excluded.page_count,
            scan_page_ratio = excluded.scan_page_ratio,
            processed_at = excluded.processed_at
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
            result.saved_bytes,
            result.saved_percent,
            result.error_message,
            pymupdf_version,
            qpdf_version,
            result.page_count,
            result.scan_page_ratio,
            processed_at,
        ),
    )
    conn.commit()


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
