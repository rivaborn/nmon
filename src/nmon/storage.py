import sqlite3
import time
from typing import Literal

from nmon.models import GPUSample, HistoryRow, sample_to_row, row_to_sample

class StorageError(RuntimeError):
    pass

class Storage:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS gpu_samples (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                gpu_index        INTEGER NOT NULL,
                gpu_uuid         TEXT    NOT NULL,
                gpu_name         TEXT    NOT NULL,
                timestamp        REAL    NOT NULL,
                temperature_c    REAL    NOT NULL,
                memory_used_mib  REAL    NOT NULL,
                memory_total_mib REAL    NOT NULL,
                power_draw_w     REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_samples_gpu_time
                ON gpu_samples (gpu_index, timestamp);
        """)
        self._conn.commit()

    def insert_samples(self, samples: list[GPUSample]) -> None:
        rows = [sample_to_row(s) for s in samples]
        try:
            self._conn.executemany(
                "INSERT INTO gpu_samples (gpu_index,gpu_uuid,gpu_name,timestamp,"
                "temperature_c,memory_used_mib,memory_total_mib,power_draw_w) "
                "VALUES (:gpu_index,:gpu_uuid,:gpu_name,:timestamp,:temperature_c,"
                ":memory_used_mib,:memory_total_mib,:power_draw_w)",
                rows
            )
            self._conn.commit()
        except sqlite3.OperationalError as e:
            raise StorageError(str(e)) from e

    def prune_old(self, retention_hours: int) -> int:
        cutoff = time.time() - retention_hours * 3600
        cur = self._conn.execute("DELETE FROM gpu_samples WHERE timestamp < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    def get_current_stats(self, gpu_index: int) -> tuple[float, float] | None:
        now = time.time()
        cur = self._conn.execute(
            "SELECT MAX(CASE WHEN timestamp >= ? THEN temperature_c END),"
            "       AVG(CASE WHEN timestamp >= ? THEN temperature_c END)"
            " FROM gpu_samples WHERE gpu_index = ?",
            (now - 86400, now - 3600, gpu_index)
        )
        row = cur.fetchone()
        if row[0] is None:
            return None
        return float(row[0]), float(row[1])

    def get_history(
        self,
        gpu_index: int,
        metric: Literal["temperature_c", "memory_used_mib", "power_draw_w"],
        since: float,
    ) -> list[HistoryRow]:
        cur = self._conn.execute(
            f"SELECT timestamp, {metric} FROM gpu_samples "
            "WHERE gpu_index = ? AND timestamp >= ? ORDER BY timestamp ASC",
            (gpu_index, since)
        )
        return [HistoryRow(timestamp=r[0], value=r[1]) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
