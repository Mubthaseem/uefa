import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import AsyncSessionLocal
from app.models.db_models import LiveEvent, EventStream

async def seed_events():
    async with AsyncSessionLocal() as session:
        # Check if events already exist
        from sqlalchemy import select
        res = await session.execute(select(LiveEvent))
        existing = res.scalars().all()
        if existing:
            print(f"[!] {len(existing)} events already exist in Supabase database.")
            return

        ev1 = LiveEvent(
            id=uuid.UUID("e42ab58b-103c-48c7-a78e-bc548178f3c7"),
            category="Football",
            league="UEFA Champions League",
            title="Real Madrid vs Manchester City",
            team_home="Real Madrid",
            team_away="Manchester City",
            team_home_badge="https://assets.dayjournal.app/badges/real_madrid.png",
            team_away_badge="https://assets.dayjournal.app/badges/man_city.png",
            scheduled_at=datetime.now(timezone.utc),
            status="live",
            score_home="2",
            score_away="1",
            live_minute="68'",
            is_featured=True,
        )

        s1_1 = EventStream(
            id=uuid.uuid4(),
            event_id=ev1.id,
            label="Primary HD (1080p 60fps)",
            stream_type="hls",
            stream_url="https://live-cdn.dayjournal.app/hls/ucl/rm_mc/master.m3u8",
            resolution="1080p",
            language="English",
            is_primary=True,
            priority=1,
        )

        s1_2 = EventStream(
            id=uuid.uuid4(),
            event_id=ev1.id,
            label="Backup Low-Latency (720p)",
            stream_type="hls",
            stream_url="https://backup-cdn.dayjournal.app/hls/ucl/rm_mc/stream_720.m3u8",
            resolution="720p",
            language="English",
            is_primary=False,
            priority=2,
        )

        s1_3 = EventStream(
            id=uuid.uuid4(),
            event_id=ev1.id,
            label="Tactical Cam / Multi-Angle",
            stream_type="hls",
            stream_url="https://live-cdn.dayjournal.app/hls/ucl/rm_mc/tactical.m3u8",
            resolution="1080p",
            language="Ambient",
            is_primary=False,
            priority=3,
        )

        ev2 = LiveEvent(
            id=uuid.UUID("9f12a102-7abc-40f5-a6c0-0455efbde98d"),
            category="Basketball",
            league="NBA",
            title="Los Angeles Lakers vs Golden State Warriors",
            team_home="Los Angeles Lakers",
            team_away="Golden State Warriors",
            team_home_badge="https://assets.dayjournal.app/badges/lakers.png",
            team_away_badge="https://assets.dayjournal.app/badges/warriors.png",
            scheduled_at=datetime.now(timezone.utc),
            status="live",
            score_home="94",
            score_away="91",
            live_minute="Q4 02:45",
            is_featured=False,
        )

        s2_1 = EventStream(
            id=uuid.uuid4(),
            event_id=ev2.id,
            label="Courtside Feed (1080p)",
            stream_type="hls",
            stream_url="https://live-cdn.dayjournal.app/hls/nba/lal_gsw/court.m3u8",
            resolution="1080p",
            language="English",
            is_primary=True,
            priority=1,
        )

        session.add_all([ev1, s1_1, s1_2, s1_3, ev2, s2_1])
        await session.commit()
        print("[+] Seeded live sports matches & HLS stream channels into Supabase!")

if __name__ == "__main__":
    asyncio.run(seed_events())