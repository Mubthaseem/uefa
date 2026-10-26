"""Admin Match & Stream Manager Endpoints."""

from datetime import datetime
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import require_admin
from app.models.db_models import Admin, EventStream, LiveEvent
from app.services.audit_service import log_audit_event
from app.services.fotmob_service import get_fotmob_match_details
from app.services.fotmob_sync_worker import sync_single_event

router = APIRouter(prefix="/v1/admin/events", tags=["Admin Match & Stream Manager"])


class FotmobPreviewIn(BaseModel):
    url_or_id: str


class EventCreateIn(BaseModel):
    category: str = "Football"
    league: str
    title: str
    team_home: str
    team_away: str
    team_home_badge: str | None = None
    team_away_badge: str | None = None
    scheduled_at: str
    status: str = "upcoming"
    score_home: str = "0"
    score_away: str = "0"
    live_minute: str = ""
    is_featured: bool = False
    fotmob_match_id: str | None = None
    auto_sync: bool = True


class EventUpdateIn(BaseModel):
    category: str | None = None
    league: str | None = None
    title: str | None = None
    team_home: str | None = None
    team_away: str | None = None
    team_home_badge: str | None = None
    team_away_badge: str | None = None
    scheduled_at: str | None = None
    status: str | None = None
    score_home: str | None = None
    score_away: str | None = None
    live_minute: str | None = None
    is_featured: bool | None = None
    fotmob_match_id: str | None = None
    auto_sync: bool | None = None


class StreamCreateIn(BaseModel):
    label: str
    stream_type: str = "hls"
    stream_url: str
    resolution: str = "1080p"
    language: str = "English"
    is_primary: bool = False
    priority: int = 0


@router.post("/fotmob/preview")
async def fotmob_preview(
    payload: FotmobPreviewIn,
    admin: Admin = Depends(require_admin()),
):
    """Fetch match preview metadata directly from FotMob."""
    try:
        data = await get_fotmob_match_details(payload.url_or_id, force_refresh=True)
        return data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not fetch FotMob match: {str(e)}"
        )


@router.post("/{event_id}/sync-fotmob")
async def manual_sync_fotmob(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_admin()),
):
    """Trigger manual sync for an event from FotMob."""
    data = await sync_single_event(str(event_id))
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found or has no FotMob match ID."
        )
    return {"status": "synced", "data": data}


@router.get("")
async def admin_list_events(
    category: str | None = None,
    status: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_admin()),
):
    stmt = select(LiveEvent).options(selectinload(LiveEvent.streams)).order_by(
        LiveEvent.scheduled_at.desc()
    ).limit(limit)

    if category:
        stmt = stmt.where(LiveEvent.category == category)
    if status:
        stmt = stmt.where(LiveEvent.status == status)

    res = await db.execute(stmt)
    events = res.scalars().all()

    items = []
    for ev in events:
        items.append({
            "id": str(ev.id),
            "category": ev.category,
            "league": ev.league,
            "title": ev.title,
            "team_home": ev.team_home,
            "team_away": ev.team_away,
            "team_home_badge": ev.team_home_badge,
            "team_away_badge": ev.team_away_badge,
            "scheduled_at": ev.scheduled_at.isoformat(),
            "status": ev.status,
            "score_home": ev.score_home,
            "score_away": ev.score_away,
            "live_minute": ev.live_minute,
            "is_featured": ev.is_featured,
            "fotmob_match_id": ev.fotmob_match_id,
            "auto_sync": ev.auto_sync,
            "last_synced_at": ev.last_synced_at.isoformat() if ev.last_synced_at else None,
            "streams": [
                {
                    "id": str(s.id),
                    "label": s.label,
                    "stream_type": s.stream_type,
                    "stream_url": s.stream_url,
                    "resolution": s.resolution,
                    "language": s.language,
                    "is_primary": s.is_primary,
                    "priority": s.priority,
                }
                for s in ev.streams
            ]
        })
    return {"items": items, "total": len(items)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def admin_create_event(
    payload: EventCreateIn,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_admin()),
):
    sched = datetime.fromisoformat(payload.scheduled_at)
    ev = LiveEvent(
        category=payload.category,
        league=payload.league,
        title=payload.title,
        team_home=payload.team_home,
        team_away=payload.team_away,
        team_home_badge=payload.team_home_badge,
        team_away_badge=payload.team_away_badge,
        scheduled_at=sched,
        status=payload.status,
        score_home=payload.score_home,
        score_away=payload.score_away,
        live_minute=payload.live_minute,
        is_featured=payload.is_featured,
        fotmob_match_id=payload.fotmob_match_id,
        auto_sync=payload.auto_sync,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    await log_audit_event(
        db,
        actor_id=admin.id,
        action="events.create",
        target_type="live_event",
        target_id=str(ev.id),
        metadata={"title": ev.title, "league": ev.league, "fotmob_match_id": ev.fotmob_match_id}
    )
    return {"id": str(ev.id), "title": ev.title}


@router.put("/{event_id}")
async def admin_update_event(
    event_id: uuid.UUID,
    payload: EventUpdateIn,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_admin()),
):
    stmt = select(LiveEvent).where(LiveEvent.id == event_id)
    res = await db.execute(stmt)
    ev = res.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    data = payload.model_dump(exclude_unset=True)
    if "scheduled_at" in data and data["scheduled_at"]:
        data["scheduled_at"] = datetime.fromisoformat(data["scheduled_at"])

    for k, v in data.items():
        setattr(ev, k, v)

    await db.commit()
    await log_audit_event(
        db,
        actor_id=admin.id,
        action="events.update",
        target_type="live_event",
        target_id=str(ev.id),
        metadata=data
    )
    return {"updated": True, "id": str(ev.id)}


@router.delete("/{event_id}")
async def admin_delete_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_admin()),
):
    stmt = select(LiveEvent).where(LiveEvent.id == event_id)
    res = await db.execute(stmt)
    ev = res.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    await db.delete(ev)
    await db.commit()

    await log_audit_event(
        db,
        actor_id=admin.id,
        action="events.delete",
        target_type="live_event",
        target_id=str(event_id),
        metadata={"title": ev.title}
    )
    return {"deleted": True}


@router.post("/{event_id}/streams", status_code=status.HTTP_201_CREATED)
async def admin_add_stream(
    event_id: uuid.UUID,
    payload: StreamCreateIn,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_admin()),
):
    stream = EventStream(
        event_id=event_id,
        label=payload.label,
        stream_type=payload.stream_type,
        stream_url=payload.stream_url,
        resolution=payload.resolution,
        language=payload.language,
        is_primary=payload.is_primary,
        priority=payload.priority,
    )
    db.add(stream)
    await db.commit()
    await db.refresh(stream)
    return {"id": str(stream.id), "label": stream.label}


@router.delete("/streams/{stream_id}")
async def admin_delete_stream(
    stream_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_admin()),
):
    stmt = select(EventStream).where(EventStream.id == stream_id)
    res = await db.execute(stmt)
    st = res.scalar_one_or_none()
    if not st:
        raise HTTPException(status_code=404, detail="Stream feed not found")

    await db.delete(st)
    await db.commit()
    return {"deleted": True}
