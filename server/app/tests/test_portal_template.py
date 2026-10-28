"""Tests for Portal Template Service and Resolution."""

import pytest
from app.services.portal_service import (
    get_file_template,
    get_portal_template,
    render_portal_html,
    seed_portal_templates_if_empty,
    update_portal_template,
    reset_portal_template_to_file,
)
from app.tests.conftest import TestingSessionLocal


@pytest.mark.asyncio
async def test_render_portal_html_token_replacement():
    """Verify runtime token placeholder replacement."""
    sample_template = "<html><body><script>const TOKEN = '{{ token }}';</script></body></html>"
    rendered = render_portal_html(sample_template, token="SECRET_JWT_123")
    assert "SECRET_JWT_123" in rendered
    assert "{{ token }}" not in rendered


@pytest.mark.asyncio
async def test_get_file_template_returns_valid_html():
    """Verify file template reads the streaming_portal.html on disk."""
    html = get_file_template("streaming_portal.html")
    assert "<!DOCTYPE html>" in html
    assert "ZetaStream" in html
    assert "Hls.isSupported()" in html


@pytest.mark.asyncio
async def test_portal_template_db_resolution_and_seeding():
    """Verify seeding and database precedence over file system."""
    async with TestingSessionLocal() as session:
        # Initially empty, get_portal_template should fallback to file
        initial_html = await get_portal_template(session, slug="streaming_portal")
        assert "ZetaStream" in initial_html

        # Run auto-seed
        await seed_portal_templates_if_empty(session)

        # Update with a custom template in the database
        custom_html = "<!DOCTYPE html><html><body><h1>Custom DB Streaming Portal</h1><p>{{ token }}</p></body></html>"
        updated = await update_portal_template(
            db=session,
            slug="streaming_portal",
            new_html=custom_html,
            title="Custom Portal"
        )
        assert updated.version >= 1
        assert updated.title == "Custom Portal"

        # Now get_portal_template should return the custom DB template
        resolved = await get_portal_template(session, slug="streaming_portal")
        assert "Custom DB Streaming Portal" in resolved

        # Render with token
        rendered = render_portal_html(resolved, token="MEMBER_TOKEN_ABC")
        assert "MEMBER_TOKEN_ABC" in rendered

        # Reset back to file
        old_version = updated.version
        reset_record = await reset_portal_template_to_file(session, slug="streaming_portal")
        assert reset_record.version > old_version
        
        resolved_after_reset = await get_portal_template(session, slug="streaming_portal")
        assert "ZetaStream" in resolved_after_reset
        assert "Custom DB Streaming Portal" not in resolved_after_reset
