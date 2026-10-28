import logging
from pathlib import Path
import time
from typing import Any
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.db_models import PortalTemplate

logger = logging.getLogger(__name__)
settings = get_settings()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
DEFAULT_STREAMING_TEMPLATE_FILE = TEMPLATES_DIR / "streaming_portal.html"

# Minimal emergency inline fallback in case disk file and database are both unavailable
EMERGENCY_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ZetaStream - Live Broadcast</title>
  <style>body { font-family: sans-serif; background: #F8FAFC; color: #0F172A; padding: 24px; text-align: center; }</style>
</head>
<body>
  <h2>Live Sports Broadcast</h2>
  <p>Streaming portal is initializing. Please tap reload.</p>
</body>
</html>"""

_github_template_cache: str | None = None
_github_template_cache_time: float = 0.0
GITHUB_CACHE_TTL_SECONDS: float = 60.0


async def fetch_github_template(url: str | None = None, force_refresh: bool = False) -> str | None:
    """
    Fetch streaming portal HTML template directly from GitHub raw URL.
    Uses an in-memory cache with a 60-second TTL.
    """
    global _github_template_cache, _github_template_cache_time
    target_url = url or getattr(
        settings,
        "PORTAL_GITHUB_RAW_URL",
        "https://raw.githubusercontent.com/Mubthaseem/uefa/main/server/app/templates/streaming_portal.html"
    )
    now = time.time()
    if not force_refresh and _github_template_cache and (now - _github_template_cache_time < GITHUB_CACHE_TTL_SECONDS):
        return _github_template_cache

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(target_url)
            if resp.status_code == 200 and len(resp.text.strip()) > 100:
                _github_template_cache = resp.text
                _github_template_cache_time = now
                logger.info(f"Loaded portal template from GitHub ({len(resp.text)} bytes)")
                return _github_template_cache
    except Exception as exc:
        logger.warning(f"Could not fetch portal template from GitHub ({target_url}): {exc}")

    return _github_template_cache


def get_file_template(filename: str = "streaming_portal.html") -> str:
    """Read template file from disk, or return emergency fallback."""
    file_path = TEMPLATES_DIR / filename
    try:
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Failed to read portal template file at {file_path}: {exc}")
    return EMERGENCY_FALLBACK_HTML


async def get_portal_template(
    db: AsyncSession,
    slug: str = "streaming_portal",
    prefer_github: bool = True
) -> str:
    """
    Tiered HTML template resolution:
    1. Primary: Load dynamically from GitHub repository (prefer_github=True).
    2. Fallback: Query Supabase database (portal_templates).
    3. Fallback: Local template file on disk.
    4. Fallback: Emergency minimal inline HTML.
    """
    if prefer_github and slug == "streaming_portal":
        github_html = await fetch_github_template()
        if github_html and github_html.strip():
            return github_html

    try:
        stmt = select(PortalTemplate).where(
            PortalTemplate.slug == slug,
            PortalTemplate.is_active == True
        )
        res = await db.execute(stmt)
        record = res.scalars().first()
        if record and record.html_content and record.html_content.strip():
            return record.html_content
    except Exception as exc:
        logger.warning(f"Database query for portal template '{slug}' failed, falling back to disk: {exc}")

    return get_file_template(f"{slug}.html")


def render_portal_html(template_str: str, token: str, install_id: str = "") -> str:
    """
    Inject runtime parameters (member token, install_id) into template.
    Supports {{ token }}, {safe_token}, and __TOKEN__ placeholders.
    """
    safe_token = token or ""
    rendered = template_str.replace("{{ token }}", safe_token)
    rendered = rendered.replace("{{token}}", safe_token)
    rendered = rendered.replace("{safe_token}", safe_token)
    rendered = rendered.replace("__TOKEN__", safe_token)
    rendered = rendered.replace("{{ install_id }}", install_id or "")
    rendered = rendered.replace("{{install_id}}", install_id or "")
    return rendered


async def seed_portal_templates_if_empty(db: AsyncSession) -> None:
    """
    Ensure the streaming_portal template exists in the database on startup.
    If absent, seeds it using the HTML file on disk.
    """
    try:
        stmt = select(PortalTemplate).where(PortalTemplate.slug == "streaming_portal")
        res = await db.execute(stmt)
        existing = res.scalars().first()
        if not existing:
            file_html = get_file_template("streaming_portal.html")
            template = PortalTemplate(
                slug="streaming_portal",
                title="Live Sports Broadcast Portal",
                html_content=file_html,
                is_active=True,
                version=1
            )
            db.add(template)
            await db.commit()
            logger.info("Successfully seeded streaming_portal template into database from file.")
    except Exception as exc:
        logger.warning(f"Auto-seeding portal template into database skipped or failed: {exc}")
        await db.rollback()


async def update_portal_template(
    db: AsyncSession,
    slug: str,
    new_html: str,
    title: str | None = None
) -> PortalTemplate:
    """
    Update or create a portal template in the database.
    Increments the template version integer.
    """
    stmt = select(PortalTemplate).where(PortalTemplate.slug == slug)
    res = await db.execute(stmt)
    existing = res.scalars().first()

    if existing:
        existing.html_content = new_html
        if title:
            existing.title = title
        existing.version += 1
        existing.is_active = True
        await db.commit()
        await db.refresh(existing)
        return existing
    else:
        new_template = PortalTemplate(
            slug=slug,
            title=title or "Live Sports Broadcast Portal",
            html_content=new_html,
            is_active=True,
            version=1
        )
        db.add(new_template)
        await db.commit()
        await db.refresh(new_template)
        return new_template


async def reset_portal_template_to_file(db: AsyncSession, slug: str = "streaming_portal") -> PortalTemplate:
    """
    Revert the database template back to the static file on disk.
    """
    file_html = get_file_template(f"{slug}.html")
    return await update_portal_template(
        db=db,
        slug=slug,
        new_html=file_html,
        title="Live Sports Broadcast Portal (Reset to File)"
    )
