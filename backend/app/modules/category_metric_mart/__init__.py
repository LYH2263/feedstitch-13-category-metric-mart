"""Category metric mart.

Builds category-level metrics from the *current* canonical master data and
stores every refresh as an immutable batch so the metric page and the master
list always trace back to the same numbers.

Metric definitions (all derived from canonical_items only, no hand counts):
- item_count  : number of canonical items in the category (件数)
- price_total : SUM(price) of canonical items in the category (价格合计)
- price_avg   : AVG(price), i.e. price_total / item_count (均价)
- price_min / price_max : MIN/MAX(price) in the category
- count_share : item_count / grand total item count

A refresh is repeatable: it recomputes the whole mart from canonical inside
one transaction and replaces the previous batch's rows with a new batch.
The batch report carries reconciliation checks (category counts sum to the
canonical total; category price totals sum to the canonical price total).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

PRICE_TOLERANCE = 0.01


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metric_refresh_runs(
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            canonical_total INTEGER NOT NULL,
            category_count INTEGER NOT NULL,
            metric_row_count INTEGER NOT NULL,
            reconciled INTEGER NOT NULL DEFAULT 0,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS category_metrics(
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            item_count INTEGER NOT NULL,
            price_total REAL NOT NULL,
            price_avg REAL NOT NULL,
            price_min REAL NOT NULL,
            price_max REAL NOT NULL,
            count_share REAL NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, category)
        );
        CREATE INDEX IF NOT EXISTS idx_category_metrics_run
            ON category_metrics(run_id);
        """
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _round2(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def _aggregate_categories(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT category,
               COUNT(*)        AS item_count,
               SUM(price)      AS price_total,
               AVG(price)      AS price_avg,
               MIN(price)      AS price_min,
               MAX(price)      AS price_max
        FROM canonical_items
        GROUP BY category
        ORDER BY category
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _build_metrics(
    conn: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compute the mart from canonical and reconcile it in the same pass."""
    canonical_total = int(
        conn.execute("SELECT COUNT(*) c FROM canonical_items").fetchone()["c"]
    )
    canonical_price_total = float(
        conn.execute(
            "SELECT COALESCE(SUM(price), 0) s FROM canonical_items"
        ).fetchone()["s"]
    )
    aggregates = _aggregate_categories(conn)

    metrics: list[dict[str, Any]] = []
    sum_item_count = 0
    sum_price_total = 0.0
    for agg in aggregates:
        item_count = int(agg["item_count"])
        price_total = _round2(agg["price_total"])
        price_avg = _round2(agg["price_avg"])
        count_share = _round2(item_count / canonical_total) if canonical_total else 0.0
        metrics.append(
            {
                "category": agg["category"],
                "item_count": item_count,
                "price_total": price_total,
                "price_avg": price_avg,
                "price_min": _round2(agg["price_min"]),
                "price_max": _round2(agg["price_max"]),
                "count_share": count_share,
            }
        )
        sum_item_count += item_count
        sum_price_total += price_total

    checks = [
        {
            "name": "category_count_sum_equals_canonical_total",
            "detail": f"sum(category.item_count)={sum_item_count} vs canonical_total={canonical_total}",
            "passed": sum_item_count == canonical_total,
        },
        {
            "name": "metric_row_count_equals_distinct_category_count",
            "detail": f"metric rows={len(metrics)} vs distinct categories={len(aggregates)}",
            "passed": len(metrics) == len(aggregates),
        },
        {
            "name": "category_price_sum_equals_canonical_price_total",
            "detail": (
                f"sum(category.price_total)={_round2(sum_price_total)} "
                f"vs canonical price_total={_round2(canonical_price_total)}"
            ),
            "passed": abs(sum_price_total - _round2(canonical_price_total)) <= PRICE_TOLERANCE,
        },
    ]
    totals = {
        "canonical_total": canonical_total,
        "category_count": len(aggregates),
        "metric_row_count": len(metrics),
        "price_total": _round2(canonical_price_total),
        "sum_item_count": sum_item_count,
        "sum_price_total": _round2(sum_price_total),
    }
    return metrics, {"checks": checks, "totals": totals}


def refresh_metrics_conn(conn: sqlite3.Connection) -> dict[str, Any]:
    """Recompute and persist the mart on an existing connection (transactional).

    Re-runnable: each call creates a new batch and replaces the previous
    batch as the latest one. Nothing is cached from an earlier refresh.
    """
    init_schema(conn)
    metrics, evidence = _build_metrics(conn)
    checks = evidence["checks"]
    totals = evidence["totals"]
    reconciled = all(c["passed"] for c in checks)
    created_at = _now()

    cur = conn.execute(
        """
        INSERT INTO metric_refresh_runs(
            status, canonical_total, category_count, metric_row_count,
            reconciled, report_json, created_at
        ) VALUES ('running', 0, 0, 0, 0, '{}', ?)
        """,
        (created_at,),
    )
    run_id = int(cur.lastrowid)

    conn.executemany(
        """
        INSERT INTO category_metrics(
            run_id, category, item_count, price_total, price_avg,
            price_min, price_max, count_share, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                run_id,
                m["category"],
                m["item_count"],
                m["price_total"],
                m["price_avg"],
                m["price_min"],
                m["price_max"],
                m["count_share"],
                created_at,
            )
            for m in metrics
        ],
    )

    report = {
        "run_id": run_id,
        "canonical_total": totals["canonical_total"],
        "category_count": totals["category_count"],
        "metric_row_count": totals["metric_row_count"],
        "canonical_price_total": totals["price_total"],
        "sum_item_count": totals["sum_item_count"],
        "sum_price_total": totals["sum_price_total"],
        "checks": checks,
        "reconciled": reconciled,
        "created_at": created_at,
        "metrics": metrics,
    }
    conn.execute(
        """
        UPDATE metric_refresh_runs
        SET status=?, canonical_total=?, category_count=?, metric_row_count=?,
            reconciled=?, report_json=?
        WHERE id=?
        """,
        (
            "ok" if reconciled else "reconcile_failed",
            totals["canonical_total"],
            totals["category_count"],
            totals["metric_row_count"],
            1 if reconciled else 0,
            json.dumps(report, ensure_ascii=False),
            run_id,
        ),
    )
    return report


def _record_failed_run(connect, exc: Exception) -> None:
    """Best-effort persistence of a failed refresh; never masks the error."""
    try:
        conn = connect()
        try:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO metric_refresh_runs(
                    status, canonical_total, category_count, metric_row_count,
                    reconciled, report_json, created_at
                ) VALUES ('failed', 0, 0, 0, 0, ?, datetime('now'))
                """,
                (json.dumps({"error": str(exc)}, ensure_ascii=False),),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def refresh_metrics(connect) -> dict[str, Any]:
    """Open a connection, run one atomic refresh, commit and return the report."""
    conn = connect()
    try:
        try:
            report = refresh_metrics_conn(conn)
            conn.commit()
            return report
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            _record_failed_run(connect, exc)
            raise
    finally:
        conn.close()


def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["report"] = json.loads(d.pop("report_json") or "{}")
    return d


def list_refresh_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    init_schema(conn)
    rows = conn.execute(
        """
        SELECT id, status, canonical_total, category_count, metric_row_count,
               reconciled, report_json, created_at
        FROM metric_refresh_runs ORDER BY id DESC
        """
    ).fetchall()
    return [_row_to_run(r) for r in rows]


def get_latest_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    init_schema(conn)
    row = conn.execute(
        """
        SELECT id, status, canonical_total, category_count, metric_row_count,
               reconciled, report_json, created_at
        FROM metric_refresh_runs ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    return _row_to_run(row) if row else None


def list_latest_metrics(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Metrics of the latest refresh batch (empty until first refresh)."""
    init_schema(conn)
    latest = conn.execute(
        "SELECT MAX(id) id FROM metric_refresh_runs"
    ).fetchone()["id"]
    if latest is None:
        return []
    rows = conn.execute(
        """
        SELECT category, item_count, price_total, price_avg,
               price_min, price_max, count_share
        FROM category_metrics WHERE run_id = ? ORDER BY category
        """,
        (latest,),
    ).fetchall()
    return [dict(r) for r in rows]


def mart_status(conn: sqlite3.Connection) -> dict[str, Any]:
    """Snapshot used by the metric page: latest batch vs live canonical."""
    init_schema(conn)
    latest_run = get_latest_run(conn)
    canonical_total = int(
        conn.execute("SELECT COUNT(*) c FROM canonical_items").fetchone()["c"]
    )
    distinct_categories = int(
        conn.execute(
            "SELECT COUNT(DISTINCT category) c FROM canonical_items"
        ).fetchone()["c"]
    )
    metrics = list_latest_metrics(conn)
    stale = (
        latest_run is not None
        and (
            latest_run["canonical_total"] != canonical_total
            or latest_run["category_count"] != distinct_categories
        )
    )
    return {
        "latest_run": latest_run,
        "canonical_total_now": canonical_total,
        "distinct_category_count_now": distinct_categories,
        "metrics": metrics,
        "stale": stale,
    }
