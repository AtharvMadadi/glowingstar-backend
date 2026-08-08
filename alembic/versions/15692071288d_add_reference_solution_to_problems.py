"""add reference_solution to problems

Revision ID: 15692071288d
Revises: 9dff68852915
Create Date: 2026-08-08 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '15692071288d'
down_revision: Union[str, Sequence[str], None] = '9dff68852915'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('problems', sa.Column('reference_solution', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('problems', 'reference_solution')
