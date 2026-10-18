"""proctor assignments, announcements

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19

Catatan vs DATABASE_DESIGN: time_extensions dan connection_events (tab_hidden) dicatat sebagai
audit_events (TIME_EXTENDED dengan metadata.seconds, TAB_HIDDEN) yang sudah append-only dan
terindeks per target; announcements.priority belum dipakai.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    create table proctor_assignments (
      exam_id uuid not null references exams (id) on delete restrict,
      user_id uuid not null references users (id) on delete restrict,
      assigned_by uuid not null references users (id) on delete restrict,
      created_at timestamptz not null default now(),
      primary key (exam_id, user_id)
    );
    create index proctor_assignments_user_idx on proctor_assignments (user_id);
    create index proctor_assignments_assigned_by_idx on proctor_assignments (assigned_by);

    create table announcements (
      id uuid primary key default gen_random_uuid(),
      exam_id uuid not null references exams (id) on delete restrict,
      created_by uuid not null references users (id) on delete restrict,
      message text not null check (length(message) between 1 and 500),
      issued_at timestamptz not null default now()
    );
    create index announcements_exam_idx on announcements (exam_id, issued_at);
    create index announcements_created_by_idx on announcements (created_by);
    """)


def downgrade() -> None:
    op.execute("drop table announcements, proctor_assignments;")
