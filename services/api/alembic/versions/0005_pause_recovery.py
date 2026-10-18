"""heartbeat, automatic pause, server outages, device switch permit, audit events

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18

Jeda yang sedang berjalan = exam_attempts.paused_at (baris pause_incidents ditulis saat insiden
ditutup). Selama jeda, batas waktu "dibekukan": sisa = deadline − paused_at; saat ditutup
deadline digeser sebesar kredit (≤300 dtk/insiden, ≤600 dtk total).
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    alter table exam_attempts
      add column last_heartbeat_at timestamptz not null default now(),
      add column paused_at timestamptz,
      add column pause_consumed_sec int not null default 0
        check (pause_consumed_sec between 0 and 600),
      add column last_tab_visible boolean,
      add column switch_permit_until timestamptz,
      add constraint exam_attempts_paused_check
        check ((state = 'PAUSED') = (paused_at is not null));
    create index exam_attempts_live_heartbeat_idx on exam_attempts (last_heartbeat_at)
      where state in ('IN_PROGRESS', 'PAUSED');

    create table pause_incidents (
      id uuid primary key default gen_random_uuid(),
      attempt_id uuid not null references exam_attempts (id) on delete restrict,
      detected_at timestamptz not null,
      resumed_at timestamptz not null,
      credited_sec int not null check (credited_sec between 0 and 300),
      end_reason text not null check (end_reason in ('RECONNECT', 'CAP'))
    );
    create index pause_incidents_attempt_idx on pause_incidents (attempt_id, resumed_at desc);

    -- Satu baris: waktu sweep terakhir. Celah besar = server/DB tidak berjalan (outage).
    create table server_clock (
      id boolean primary key default true check (id),
      last_sweep_at timestamptz not null default now()
    );
    insert into server_clock default values;

    create table server_outages (
      id uuid primary key default gen_random_uuid(),
      started_at timestamptz not null,
      ended_at timestamptz not null,
      credited_sec int not null,
      affected_attempts int not null
    );

    create table audit_events (
      id uuid primary key default gen_random_uuid(),
      actor_id uuid references users (id) on delete restrict,
      action text not null,
      target_type text not null,
      target_id uuid not null,
      reason text,
      metadata jsonb not null default '{}',
      created_at timestamptz not null default now()
    );
    create index audit_events_actor_idx on audit_events (actor_id);
    create index audit_events_target_idx on audit_events (target_type, target_id, created_at desc);
    """)


def downgrade() -> None:
    op.execute("""
    drop table audit_events, server_outages, server_clock, pause_incidents;
    drop index exam_attempts_live_heartbeat_idx;
    alter table exam_attempts
      drop constraint exam_attempts_paused_check,
      drop column switch_permit_until, drop column last_tab_visible,
      drop column pause_consumed_sec, drop column paused_at, drop column last_heartbeat_at;
    """)
