"""002 Seed Configuration and Flags

Revision ID: 002_seed_config
Revises: 001_initial_schema
Create Date: 2026-10-26 12:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "002_seed_config"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Seed app_config (Spec 5.8)
    op.execute("""
        INSERT INTO app_config (key, value) VALUES
        ('brand.app_name', '"DayJournal"'),
        ('brand.tagline', '"Your private daily journal"'),
        ('brand.primary_color', '"#4F6DF5"'),
        ('members.enabled', 'true'),
        ('members.tab_label', '"Members"'),
        ('members.locked_title', '"Members area"'),
        ('members.locked_body', '"Enter an access code to unlock."'),
        ('members.redeem_field_label', '"Access code"'),
        ('members.redeem_button_label', '"Unlock"'),
        ('members.redeem_success_message', '"Members area unlocked."'),
        ('members.redeem_error_message', '"That code is not valid."'),
        ('members.base_url', 'null'),
        ('journal.export_pdf', 'true'),
        ('journal.export_text', 'true'),
        ('journal.reminders', 'false'),
        ('system.config_version', '1');
    """)

    # Seed feature_flags (Spec 5.7)
    op.execute("""
        INSERT INTO feature_flags (key, value) VALUES
        ('members.enabled', 'true'),
        ('journal.export_pdf', 'true'),
        ('journal.export_text', 'true'),
        ('journal.reminders', 'false');
    """)


def downgrade() -> None:
    op.execute("DELETE FROM app_config;")
    op.execute("DELETE FROM feature_flags;")
