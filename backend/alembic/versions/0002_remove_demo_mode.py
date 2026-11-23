"""remove demo mode: drop demo_instances table and aws_connections.is_demo

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # demo connections never had a real AWS role behind them
    op.execute("DELETE FROM aws_connections WHERE is_demo")
    op.drop_table('demo_instances')
    with op.batch_alter_table('aws_connections') as b:
        b.drop_column('is_demo')


def downgrade() -> None:
    with op.batch_alter_table('aws_connections') as b:
        b.add_column(sa.Column('is_demo', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        'demo_instances',
        sa.Column('connection_id', sa.Uuid(), nullable=False),
        sa.Column('instance_id', sa.String(length=32), nullable=False),
        sa.Column('region', sa.String(length=32), nullable=False),
        sa.Column('instance_type', sa.String(length=32), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('cpu_credits', sa.String(length=16), nullable=True),
        sa.Column('public_ip', sa.String(length=64), nullable=True),
        sa.Column('has_eip', sa.Boolean(), nullable=False),
        sa.Column('fail_resize', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['connection_id'], ['aws_connections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connection_id', 'instance_id', name='uq_demo_instance'),
    )
