import json
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos.domain import AuditRecord, MetricDefinition, MetricEntry
from lifeos.task_api import get_actor, get_session

router = APIRouter(prefix="/api/metrics")
MetricType = Literal["numeric", "boolean", "categorical", "duration", "count", "rating", "text"]


class MetricCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=200)
    data_type: MetricType
    unit: str | None = Field(default=None, max_length=80)


class MetricUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    unit: str | None = Field(default=None, max_length=80)
    status: Literal["active", "archived"] | None = None


class MetricEntryCreate(BaseModel):
    recorded_on: date
    value: Any
    source: str | None = Field(default=None, max_length=300)
    estimated: bool = False


def _serialize_metric(metric: MetricDefinition) -> dict[str, Any]:
    return {column.name: getattr(metric, column.name) for column in metric.__table__.columns}


def _serialize_entry(entry: MetricEntry, metric: MetricDefinition) -> dict[str, Any]:
    return {
        "id": entry.id,
        "metric_id": entry.metric_id,
        "slug": metric.slug,
        "recorded_on": entry.recorded_on,
        "value": json.loads(entry.value),
        "source": entry.source,
        "estimated": entry.estimated,
        "created_at": entry.created_at,
    }


def _validate_value(metric: MetricDefinition, value: Any) -> None:
    kind = metric.data_type
    valid = {
        "numeric": isinstance(value, (int, float)) and not isinstance(value, bool),
        "duration": isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0,
        "count": isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        "rating": isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 10,
        "boolean": isinstance(value, bool),
        "categorical": isinstance(value, str),
        "text": isinstance(value, str),
    }[kind]
    if not valid:
        raise HTTPException(status_code=422, detail=f"value does not match metric type {kind}")


def _audit(session: Session, entity_id: int, action: str, actor: str, payload: dict[str, Any]) -> None:
    session.add(
        AuditRecord(
            entity_type="metric_entry",
            entity_id=entity_id,
            action=action,
            actor=actor,
            payload=json.dumps(payload, default=str, sort_keys=True),
        )
    )


@router.get("")
def list_metrics(_actor: str = Depends(get_actor), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [
        _serialize_metric(metric)
        for metric in session.scalars(select(MetricDefinition).order_by(MetricDefinition.slug))
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_metric(
    payload: MetricCreate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    metric = MetricDefinition(
        slug=payload.slug,
        label=payload.label.strip(),
        data_type=payload.data_type,
        unit=payload.unit.strip() if payload.unit else None,
    )
    session.add(metric)
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Metric slug already exists") from exc
    session.refresh(metric)
    return _serialize_metric(metric)


@router.patch("/{metric_id}")
def update_metric(
    metric_id: int, payload: MetricUpdate, _actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    metric = session.get(MetricDefinition, metric_id)
    if metric is None:
        raise HTTPException(status_code=404, detail="Metric not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(metric, field, value.strip() if isinstance(value, str) and field in {"label", "unit"} else value)
    session.commit()
    session.refresh(metric)
    return _serialize_metric(metric)


@router.get("/{metric_id}/entries")
def list_entries(
    metric_id: int, _actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    metric = session.get(MetricDefinition, metric_id)
    if metric is None:
        raise HTTPException(status_code=404, detail="Metric not found")
    entries = session.scalars(
        select(MetricEntry).where(MetricEntry.metric_id == metric_id).order_by(MetricEntry.recorded_on, MetricEntry.id)
    )
    return [_serialize_entry(entry, metric) for entry in entries]


@router.post("/{metric_id}/entries", status_code=status.HTTP_201_CREATED)
def create_entry(
    metric_id: int,
    payload: MetricEntryCreate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    metric = session.get(MetricDefinition, metric_id)
    if metric is None:
        raise HTTPException(status_code=404, detail="Metric not found")
    if metric.status != "active":
        raise HTTPException(status_code=409, detail="Metric is archived")
    _validate_value(metric, payload.value)
    entry = MetricEntry(
        metric_id=metric_id,
        recorded_on=payload.recorded_on,
        value=json.dumps(payload.value, sort_keys=True),
        source=payload.source,
        estimated=payload.estimated,
    )
    session.add(entry)
    session.flush()
    _audit(session, entry.id, "created", actor, payload.model_dump())
    session.commit()
    session.refresh(entry)
    return _serialize_entry(entry, metric)
