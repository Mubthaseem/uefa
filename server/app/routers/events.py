"""Public / Member Live Events & Streams API Endpoints."""

from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.models.db_models import EventStream, LiveEvent
from app.security import sign_media_url
from app.services.fotmob_service import get_fotmob_match_details

router = APIRouter(prefix="/v1/events", tags=["Live Events & Streams"])
settings = get_settings()


class StreamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    label: str
    stream_type: str
    stream_url: str
    resolution: str
    language: str
    is_primary: bool
    priority: int


class LiveEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    category: str
    league: str
    title: str
    team_home: str
    team_away: str
    team_home_badge: str | None = None
    team_away_badge: str | None = None
    scheduled_at: str
    status: str
    score_home: str | None = "0"
    score_away: str | None = "0"
    live_minute: str | None = ""
    is_featured: bool = False
    fotmob_match_id: str | None = None
    streams_count: int = 0


@router.get("", response_model=list[LiveEventOut])
async def list_live_events(
    category: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List scheduled, live, and recently ended matches/events."""
    stmt = select(LiveEvent).options(selectinload(LiveEvent.streams)).order_by(
        LiveEvent.status.desc(), LiveEvent.scheduled_at.asc()
    ).limit(limit)

    if category:
        stmt = stmt.where(LiveEvent.category == category)
    if status:
        stmt = stmt.where(LiveEvent.status == status)

    res = await db.execute(stmt)
    events = res.scalars().all()

    out = []
    for ev in events:
        out.append(LiveEventOut(
            id=ev.id,
            category=ev.category,
            league=ev.league,
            title=ev.title,
            team_home=ev.team_home,
            team_away=ev.team_away,
            team_home_badge=ev.team_home_badge,
            team_away_badge=ev.team_away_badge,
            scheduled_at=ev.scheduled_at.isoformat(),
            status=ev.status,
            score_home=ev.score_home,
            score_away=ev.score_away,
            live_minute=ev.live_minute,
            is_featured=ev.is_featured,
            fotmob_match_id=ev.fotmob_match_id,
            streams_count=len(ev.streams)
        ))
    return out


@router.get("/{event_id}", response_model=LiveEventOut)
async def get_live_event_detail(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve full details for an individual event."""
    stmt = select(LiveEvent).where(LiveEvent.id == event_id).options(selectinload(LiveEvent.streams))
    res = await db.execute(stmt)
    ev = res.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    return LiveEventOut(
        id=ev.id,
        category=ev.category,
        league=ev.league,
        title=ev.title,
        team_home=ev.team_home,
        team_away=ev.team_away,
        team_home_badge=ev.team_home_badge,
        team_away_badge=ev.team_away_badge,
        scheduled_at=ev.scheduled_at.isoformat(),
        status=ev.status,
        score_home=ev.score_home,
        score_away=ev.score_away,
        live_minute=ev.live_minute,
        is_featured=ev.is_featured,
        fotmob_match_id=ev.fotmob_match_id,
        streams_count=len(ev.streams)
    )


@router.get("/{event_id}/live")
async def get_live_match_stats(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve rich FotMob live details (lineup, live ticker, stats, momentum)."""
    stmt = select(LiveEvent).where(LiveEvent.id == event_id)
    res = await db.execute(stmt)
    ev = res.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    if not ev.fotmob_match_id:
        return {
            "status": ev.status,
            "score_home": ev.score_home,
            "score_away": ev.score_away,
            "live_minute": ev.live_minute,
            "rich_details": None,
        }

    try:
        data = await get_fotmob_match_details(ev.fotmob_match_id)
        return {
            "status": data["status"],
            "score_home": data["score_home"],
            "score_away": data["score_away"],
            "live_minute": data["live_minute"],
            "rich_details": data.get("rich_details"),
        }
    except Exception:
        return {
            "status": ev.status,
            "score_home": ev.score_home,
            "score_away": ev.score_away,
            "live_minute": ev.live_minute,
            "rich_details": ev.fotmob_data,
        }


@router.get("/{event_id}/streams", response_model=list[StreamOut])
async def get_event_streams(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Fetch active stream sources for a match with secure signed playback URLs."""
    stmt = select(EventStream).where(EventStream.event_id == event_id).order_by(EventStream.priority.asc())
    res = await db.execute(stmt)
    streams = res.scalars().all()

    out = []
    for s in streams:
        signed_url = sign_media_url(
            base_url=settings.API_HOST,
            object_path=s.stream_url,
            secret_bytes=settings.signed_url_secret_bytes,
            expires_in_seconds=3600
        )
        out.append(StreamOut(
            id=s.id,
            label=s.label,
            stream_type=s.stream_type,
            stream_url=signed_url,
            resolution=s.resolution,
            language=s.language,
            is_primary=s.is_primary,
            priority=s.priority
        ))
    return out
