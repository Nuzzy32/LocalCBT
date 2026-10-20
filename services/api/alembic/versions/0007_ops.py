"""backup jobs, ops settings (retensi backup)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20

Hasil preflight, probe jaringan, dan atestasi manual dicatat sebagai audit_events
(PREFLIGHT_SERVER, NETWORK_PROBE, NETWORK_ATTESTED; target_type 'network').
Retensi nilai/log (OQ-07) menunggu keputusan sekolah; di sini baru retensi backup.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    create table backup_jobs (
      id uuid primary key default gen_random_uuid(),
      trigger text not null check (trigger in ('DAILY', 'MANUAL', 'PRE_UPGRADE')),
      status text not null default 'QUEUED'
        check (status in ('QUEUED', 'RUNNING', 'VERIFIED', 'FAILED')),
      path text,
      alembic_rev text,
      size_bytes bigint,
      error text,
      requested_by uuid references users (id) on delete restrict,
      created_at timestamptz not null default now(),
      started_at timestamptz,
      verified_at timestamptz,
      restore_verified_at timestamptz,
      pruned_at timestamptz
    );
    create index backup_jobs_created_idx on backup_jobs (created_at desc);
    create index backup_jobs_requested_by_idx on backup_jobs (requested_by);
    create unique index backup_jobs_one_active_idx on backup_jobs ((true))
      where status in ('QUEUED', 'RUNNING');

    -- Satu baris. Nilai awal = usulan; masa simpan final ditetapkan sekolah (BR-23, OQ-07).
    create table ops_settings (
      id boolean primary key default true check (id),
      backup_hour int not null default 2 check (backup_hour between 0 and 23),
      backup_keep_daily int not null default 14 check (backup_keep_daily between 1 and 365),
      backup_keep_manual_days int not null default 90
        check (backup_keep_manual_days between 1 and 3650),
      updated_by uuid references users (id) on delete restrict,
      updated_at timestamptz not null default now()
    );
    insert into ops_settings default values;
    """)


def downgrade() -> None:
    op.execute("drop table ops_settings, backup_jobs;")
