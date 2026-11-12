"""Tests for the category metric mart: build, reconcile, repeatable refresh."""

import pytest

from app import seed
from app.db import connect
from app.modules.category_metric_mart import (
    list_latest_metrics,
    list_refresh_runs,
    mart_status,
    refresh_metrics,
)
from app.services.ingest_service import run_ingest


@pytest.fixture()
def db(monkeypatch, tmp_path):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test_app.db")
    seed.init_db()
    yield


def _ingest_all_sources():
    # alpha(3 clean) -> beta(1 conflict + 2 new) -> gamma(2 new)
    run_ingest(1, "incremental")
    run_ingest(2, "incremental")
    run_ingest(3, "incremental")


def test_refresh_builds_reconciled_mart(db):
    _ingest_all_sources()
    report = refresh_metrics(connect)

    assert report["reconciled"] is True
    assert report["canonical_total"] == 7
    assert report["category_count"] == 6
    assert report["metric_row_count"] == 6
    assert report["sum_item_count"] == 7
    assert report["canonical_price_total"] == 547.0
    assert all(c["passed"] for c in report["checks"])

    metrics = {m["category"]: m for m in list_latest_metrics(connect())}
    assert metrics["kitchen"]["item_count"] == 2
    assert metrics["kitchen"]["price_total"] == 54.0
    assert metrics["kitchen"]["price_avg"] == 27.0
    assert metrics["lighting"]["item_count"] == 1
    assert metrics["lighting"]["price_total"] == 129.0  # beta's 99.0 was quarantined


def test_refresh_is_repeatable_and_idempotent(db):
    _ingest_all_sources()
    first = refresh_metrics(connect)
    second = refresh_metrics(connect)

    assert second["run_id"] == first["run_id"] + 1
    assert second["reconciled"] is True
    assert second["canonical_total"] == first["canonical_total"] == 7

    runs = list_refresh_runs(connect())
    assert len(runs) == 2
    # only the latest batch is exposed on the mart page
    assert len(list_latest_metrics(connect())) == 6

    conn = connect()
    # every batch is persisted and queryable, nothing silently overwritten
    persisted = conn.execute(
        "SELECT run_id, COUNT(*) c FROM category_metrics GROUP BY run_id ORDER BY run_id"
    ).fetchall()
    assert [r["c"] for r in persisted] == [6, 6]
    conn.close()


def test_refresh_tracks_master_data_changes(db):
    _ingest_all_sources()
    refresh_metrics(connect)

    conn = connect()
    # master data changes: retire the only lighting item and reprice a shelf
    conn.execute("DELETE FROM canonical_items WHERE business_key = 'SKU-1001'")
    conn.execute(
        "UPDATE canonical_items SET price = 299.5 WHERE business_key = 'SKU-1002'"
    )
    conn.commit()
    conn.close()

    status = mart_status(connect())
    assert status["stale"] is True
    assert status["canonical_total_now"] == 6
    assert status["distinct_category_count_now"] == 5

    report = refresh_metrics(connect)
    assert report["reconciled"] is True
    assert report["canonical_total"] == 6
    assert report["category_count"] == 5
    assert report["metric_row_count"] == 5
    assert report["sum_item_count"] == 6
    # 547 - 129 (deleted lamp) + 50 (shelf repriced 249.5 -> 299.5)
    assert report["canonical_price_total"] == 468.0

    metrics = {m["category"]: m for m in list_latest_metrics(connect())}
    assert "lighting" not in metrics
    assert metrics["furniture"]["price_total"] == 299.5

    status_after = mart_status(connect())
    assert status_after["stale"] is False


def test_refresh_on_empty_canonical_reconciles(db):
    report = refresh_metrics(connect)
    assert report["reconciled"] is True
    assert report["canonical_total"] == 0
    assert report["category_count"] == 0
    assert report["metric_row_count"] == 0
    assert list_latest_metrics(connect()) == []


def test_failed_refresh_rolls_back_and_is_recorded(db):
    _ingest_all_sources()
    conn = connect()
    conn.execute("DROP TABLE canonical_items")
    conn.commit()
    conn.close()

    with pytest.raises(Exception):  # noqa: B017, PT011
        refresh_metrics(connect)

    runs = list_refresh_runs(connect())
    assert runs[0]["status"] == "failed"
