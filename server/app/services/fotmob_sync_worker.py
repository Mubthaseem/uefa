"""Background Worker for Auto-Syncing Live FotMob Match Data."""

import asyncio
from datetime import UTC, datetime, timedelta
import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models.db_models import LiveEvent
from app.services.fotmob_service import get_fotmob_match_details

logger = logging.getLogger("fotmob_sync_worker")

_WORKER_TASK: asyncio.Task | None = None
_RUNNING = False
SYNC_INTERVAL_SECONDS = 30


async def sync_single_event(event_id: str) -> dict | None:
    """Explicitly sync a single event from FotMob and commit changes."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LiveEvent).where(LiveEvent.id == event_id)
        )
        event = result.scalar_one_or_none()
        if not event or not event.fotmob_match_id:
            return None

        try:
            data = await get_fotmob_match_details(event.fotmob_match_id, force_refresh=True)
            event.score_home = data["score_home"]
            event.score_away = data["score_away"]
            event.live_minute = data["live_minute"]
            event.status = data["status"]
            event.fotmob_data = data["rich_details"]
            event.last_synced_at = datetime.now(UTC)
            await session.commit()
            return data
        except Exception as e:
            logger.error(f"Error syncing event {event_id} from FotMob: {e}")
            await session.rollback()
            return None


async def _sync_loop():
    """Background polling loop for active/live events."""
    global _RUNNING
    _RUNNING = True
    logger.info("Starting FotMob Live Match Auto-Sync worker...")

    while _RUNNING:
        try:
            now = datetime.now(UTC)
            # Find live matches, or upcoming matches starting within 30 minutes
            upcoming_window = now + timedelta(minutes=30)
            
            async with AsyncSessionLocal() as session:
                stmt = select(LiveEvent).where(
                    LiveEvent.auto_sync.is_(True),
                    LiveEvent.fotmob_match_id.isnot(None),
                    or_(
                        LiveEvent.status == "live",
                        (LiveEvent.status == "upcoming") & (LiveEvent.scheduled_at <= upcoming_window),
                    )
                )
                result = await session.execute(stmt)
                events = result.scalars().all()

                for ev in events:
                    try:
                        data = await get_fotmob_match_details(ev.fotmob_match_id, force_refresh=True)
                        changed = (
                            ev.score_home != data["score_home"] or
                            ev.score_away != data["score_away"] or
                            ev.status != data["status"] or
                            ev.live_minute != data["live_minute"]
                        )
                        ev.score_home = data["score_home"]
                        ev.score_away = data["score_away"]
                        ev.live_minute = data["live_minute"]
                        ev.status = data["status"]
                        ev.fotmob_data = data["rich_details"]
                        ev.last_synced_at = datetime.now(UTC)
                        
                        if changed:
                            logger.info(
                                f"FotMob Sync: {ev.title} updated -> {ev.score_home}-{ev.score_away} ({ev.status} {ev.live_minute})"
                            )
                    except Exception as err:
                        logger.warning(f"Failed sync for event {ev.id} ({ev.fotmob_match_id}): {err}")

                await session.commit()

        except Exception as e:
            logger.error(f"Error in FotMob sync worker tick: {e}", exc_info=True)

        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


def start_fotmob_worker():
    """Start background sync task."""
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(_sync_loop())


def stop_fotmob_worker():
    """Gracefully stop sync task."""
    global _RUNNING, _WORKER_TASK
    _RUNNING = False
    if _WORKER_TASK:
        _WORKER_TASK.cancel()
        _WORKER_TASK = None
