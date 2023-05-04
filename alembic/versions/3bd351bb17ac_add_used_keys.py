"""add used-keys

Revision ID: 3bd351bb17ac
Revises: 
Create Date: 2023-05-03 13:07:25.452561

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "3bd351bb17ac"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "used_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("pvtkey", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_used_keys_user_id"), "used_keys", ["user_id"], unique=False)
    op.add_column("users", sa.Column("export_at", sa.DateTime(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("users", "export_at")
    op.drop_index(op.f("ix_used_keys_user_id"), table_name="used_keys")
    op.drop_table("used_keys")
    # ### end Alembic commands ###
