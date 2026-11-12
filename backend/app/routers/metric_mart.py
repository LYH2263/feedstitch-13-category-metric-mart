from fastapi import APIRouter, HTTPException

from app.services import metric_service

router = APIRouter(tags=["metric-mart"])


@router.get("/metric-mart")
def get_mart():
    """Latest category metrics + live canonical snapshot + reconcile report."""
    return metric_service.get_mart()


@router.post("/metric-mart/refresh")
def refresh_mart():
    """Recompute the whole mart from current canonical; repeatable."""
    try:
        return metric_service.refresh()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc


@router.get("/metric-mart/runs")
def list_refresh_runs():
    return metric_service.get_refresh_runs()
