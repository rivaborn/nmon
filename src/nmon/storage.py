import sqlite3
import threading
import time
from typing import Literal, NamedTuple

from nmon.models import GPUSample, HistoryRow, OllamaSample, sample_to_row, row_to_sample

class StorageError(RuntimeError):
    pass


# Column names that may be interpolated into a query as a metric/series.
# Column names can't be bound as SQL parameters, so get_history /
# get_ollama_history build them into the query text — guard against anything
# outside these allowlists so the interpolation can never become injection.
_GPU_HISTORY_COLUMNS = frozenset({
    "temperature_c", "memory_used_mib", "power_draw_w",
    "hotspot_temp_c", "memory_junction_temp_c",
})
_OLLAMA_HISTORY_COLUMNS = frozenset({"gpu_pct", "cpu_pct"})


class CurrentStats(NamedTuple):
    """Aggregated temperature stats for one GPU. The hotspot/junction fields
    are None on cards that don't expose those sensors. Named (rather than a
    bare tuple) so positional unpacking mistakes surface at the call site."""
    max_temp_24h: float
    avg_temp_1h: float
    hotspot_max_24h: float | None
    hotspot_avg_1h: float | None
    junction_max_24h: float | None
    junction_avg_1h: float | None


class Storage:
    def __init__(self, db_path: str) -> None:
        # A single connection is shared between the collector (writes) and the
        # TUI (reads). WAL gives DB-level concurrency, but one Python
        # connection still has a single transaction context, so every access
        # is serialized through this lock to avoid one thread's commit landing
        # on another thread's in-flight statement.
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        # Runs once during __init__, before any other thread can touch the
        # connection, so it doesn't take the lock.
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS gpu_samples (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                gpu_index              INTEGER NOT NULL,
                gpu_uuid               TEXT    NOT NULL,
                gpu_name               TEXT    NOT NULL,
                timestamp              REAL    NOT NULL,
                temperature_c          REAL    NOT NULL,
                memory_used_mib        REAL    NOT NULL,
                memory_total_mib       REAL    NOT NULL,
                power_draw_w           REAL    NOT NULL,
                hotspot_temp_c         REAL,
                memory_junction_temp_c REAL
            );
            CREATE INDEX IF NOT EXISTS idx_samples_gpu_time
                ON gpu_samples (gpu_index, timestamp);
            CREATE TABLE IF NOT EXISTS ollama_samples (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       REAL    NOT NULL,
                running         INTEGER NOT NULL,
                model_name      TEXT,
                size_bytes      INTEGER NOT NULL,
                size_vram_bytes INTEGER NOT NULL,
                gpu_pct         REAL    NOT NULL,
                cpu_pct         REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ollama_time
                ON ollama_samples (timestamp);
        """)
        # Migrate legacy schemas. Earlier nmon versions stored GPU
        # hotspot temperature in a column mislabelled memory_junction_temp_c.
        # If we find that old shape, rename the column to hotspot_temp_c
        # and add a fresh memory_junction_temp_c for the real sensor.
        cols = {row[1] for row in self._conn.execute(
            "PRAGMA table_info(gpu_samples)"
        ).fetchall()}
        if "hotspot_temp_c" not in cols:
            if "memory_junction_temp_c" in cols:
                self._conn.execute(
                    "ALTER TABLE gpu_samples "
                    "RENAME COLUMN memory_junction_temp_c TO hotspot_temp_c"
                )
            else:
                self._conn.execute(
                    "ALTER TABLE gpu_samples ADD COLUMN hotspot_temp_c REAL"
                )
        cols = {row[1] for row in self._conn.execute(
            "PRAGMA table_info(gpu_samples)"
        ).fetchall()}
        if "memory_junction_temp_c" not in cols:
            self._conn.execute(
                "ALTER TABLE gpu_samples ADD COLUMN memory_junction_temp_c REAL"
            )
        self._conn.commit()

    def insert_samples(self, samples: list[GPUSample]) -> None:
        rows = [sample_to_row(s) for s in samples]
        try:
            with self._lock:
                self._conn.executemany(
                    "INSERT INTO gpu_samples (gpu_index,gpu_uuid,gpu_name,timestamp,"
                    "temperature_c,memory_used_mib,memory_total_mib,power_draw_w,"
                    "hotspot_temp_c,memory_junction_temp_c) "
                    "VALUES (:gpu_index,:gpu_uuid,:gpu_name,:timestamp,:temperature_c,"
                    ":memory_used_mib,:memory_total_mib,:power_draw_w,"
                    ":hotspot_temp_c,:memory_junction_temp_c)",
                    rows
                )
                self._conn.commit()
        except sqlite3.OperationalError as e:
            raise StorageError(str(e)) from e

    def prune_old(self, retention_hours: int) -> int:
        cutoff = time.time() - retention_hours * 3600
        with self._lock:
            cur = self._conn.execute("DELETE FROM gpu_samples WHERE timestamp < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def get_current_stats(self, gpu_index: int) -> "CurrentStats | None":
        """Aggregated temperature stats for a GPU, or None if no samples
        recorded for it."""
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "SELECT MAX(CASE WHEN timestamp >= ? THEN temperature_c END),"
                "       AVG(CASE WHEN timestamp >= ? THEN temperature_c END),"
                "       MAX(CASE WHEN timestamp >= ? THEN hotspot_temp_c END),"
                "       AVG(CASE WHEN timestamp >= ? THEN hotspot_temp_c END),"
                "       MAX(CASE WHEN timestamp >= ? THEN memory_junction_temp_c END),"
                "       AVG(CASE WHEN timestamp >= ? THEN memory_junction_temp_c END)"
                " FROM gpu_samples WHERE gpu_index = ?",
                (
                    now - 86400, now - 3600,
                    now - 86400, now - 3600,
                    now - 86400, now - 3600,
                    gpu_index,
                ),
            )
            row = cur.fetchone()
        if row[0] is None:
            return None

        def _f(v):
            return float(v) if v is not None else None

        # The 24h max (row[0]) is guaranteed non-None past the guard above,
        # but the 1h average (row[1]) can still be NULL: a GPU may have
        # samples in the last 24h yet none within the last hour (the collector
        # stalled, or resumed after a gap). Fall back to the 24h max so the two
        # required core stats are always real floats and never crash the
        # dashboard on float(None). Hotspot/junction stay optional via _f.
        max_temp_24h = float(row[0])
        avg_temp_1h = float(row[1]) if row[1] is not None else max_temp_24h

        return CurrentStats(
            max_temp_24h, avg_temp_1h,
            _f(row[2]), _f(row[3]),
            _f(row[4]), _f(row[5]),
        )

    def get_history(
        self,
        gpu_index: int,
        metric: Literal[
            "temperature_c", "memory_used_mib", "power_draw_w",
            "hotspot_temp_c", "memory_junction_temp_c",
        ],
        since: float,
        buckets: int | None = None,
    ) -> list[HistoryRow]:
        """History rows for a GPU metric since `since`.

        When `buckets` is given, the window is divided into that many equal
        time buckets and the peak (MAX) value per non-empty bucket is returned
        — this caps the row count regardless of window size and preserves
        spikes (a nearest-sample thinning in Python would drop them)."""
        if metric not in _GPU_HISTORY_COLUMNS:
            raise ValueError(f"unknown history column: {metric!r}")
        with self._lock:
            if buckets and buckets > 0:
                width = max((time.time() - since) / buckets, 1e-9)
                cur = self._conn.execute(
                    f"SELECT MIN(timestamp) AS ts, MAX({metric}) AS v "
                    "FROM gpu_samples "
                    f"WHERE gpu_index = ? AND timestamp >= ? AND {metric} IS NOT NULL "
                    "GROUP BY CAST((timestamp - ?) / ? AS INTEGER) "
                    "ORDER BY ts ASC",
                    (gpu_index, since, since, width),
                )
            else:
                cur = self._conn.execute(
                    f"SELECT timestamp, {metric} FROM gpu_samples "
                    f"WHERE gpu_index = ? AND timestamp >= ? AND {metric} IS NOT NULL "
                    "ORDER BY timestamp ASC",
                    (gpu_index, since)
                )
            return [HistoryRow(timestamp=r[0], value=r[1]) for r in cur.fetchall()]

    # ---- Ollama ------------------------------------------------------

    def insert_ollama_sample(self, sample: OllamaSample) -> None:
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO ollama_samples (timestamp,running,model_name,"
                    "size_bytes,size_vram_bytes,gpu_pct,cpu_pct) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        sample.timestamp,
                        1 if sample.running else 0,
                        sample.model_name,
                        sample.size_bytes,
                        sample.size_vram_bytes,
                        sample.gpu_pct,
                        sample.cpu_pct,
                    ),
                )
                self._conn.commit()
        except sqlite3.OperationalError as e:
            raise StorageError(str(e)) from e

    def prune_old_ollama(self, retention_hours: int) -> int:
        cutoff = time.time() - retention_hours * 3600
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM ollama_samples WHERE timestamp < ?", (cutoff,)
            )
            self._conn.commit()
            return cur.rowcount

    def get_ollama_history(
        self,
        metric: Literal["gpu_pct", "cpu_pct"],
        since: float,
        buckets: int | None = None,
    ) -> list[HistoryRow]:
        if metric not in _OLLAMA_HISTORY_COLUMNS:
            raise ValueError(f"unknown history column: {metric!r}")
        with self._lock:
            if buckets and buckets > 0:
                width = max((time.time() - since) / buckets, 1e-9)
                cur = self._conn.execute(
                    f"SELECT MIN(timestamp) AS ts, MAX({metric}) AS v "
                    "FROM ollama_samples "
                    "WHERE timestamp >= ? AND running = 1 "
                    "GROUP BY CAST((timestamp - ?) / ? AS INTEGER) "
                    "ORDER BY ts ASC",
                    (since, since, width),
                )
            else:
                cur = self._conn.execute(
                    f"SELECT timestamp, {metric} FROM ollama_samples "
                    f"WHERE timestamp >= ? AND running = 1 "
                    "ORDER BY timestamp ASC",
                    (since,),
                )
            return [HistoryRow(timestamp=r[0], value=r[1]) for r in cur.fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
