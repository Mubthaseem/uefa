"""003 Code Export Plaintext Ciphertext Column

Revision ID: 003_code_export
Revises: 002_seed_config
Create Date: 2026-10-26 12:20:00.000000

"""
import sqlalchemy as sa

from alembic import op

revision = "003_code_export"
down_revision = "002_seed_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add plaintext_ciphertext column to access_keys (Spec 6.11 Note A)
    op.add_column("access_keys", sa.Column("plaintext_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("access_keys", "plaintext_ciphertext")
