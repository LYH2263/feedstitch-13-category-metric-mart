"""Service entry points for the category metric mart."""

from __future__ import annotations

from typing import Any

from app.db import connect
from app.modules.category_metric_mart import (
    list_latest_metrics,
    list_refresh_runs,
    mart_status,
    refresh_metrics,
)


def refresh() -> dict[str, Any]:
    return refresh_metrics(connect)


def get_mart() -> dict[str, Any]:
    conn = connect()
    try:
        return mart_status(conn)
    finally:
        conn.close()


def get_metrics() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return list_latest_metrics(conn)
    finally:
        conn.close()


def get_refresh_runs() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return list_refresh_runs(conn)
    finally:
        conn.close()
