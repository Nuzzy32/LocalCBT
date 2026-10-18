"""identity, sessions, academic, import jobs

Revision ID: 0001
Revises:
Create Date: 2026-10-18

Catatan vs DATABASE_DESIGN §3: tabel roles/students/teachers dilebur ke users + user_roles
(NIS = users.username, nama = display_name). Tambahkan tabel profil bila sekolah butuh
kolom khusus siswa/guru.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    create table users (
      id uuid primary key default gen_random_uuid(),
      username text not null check (length(username) between 1 and 64),
      password_hash text not null,
      display_name text not null check (length(display_name) between 1 and 160),
      status text not null default 'ACTIVE' check (status in ('ACTIVE', 'DISABLED')),
      created_at timestamptz not null default now(),
      password_changed_at timestamptz not null default now()
    );
    create unique index users_username_lower_key on users (lower(username));

    create table user_roles (
      user_id uuid not null references users (id) on delete restrict,
      role text not null check (role in ('ADMIN', 'TEACHER', 'PROCTOR', 'STUDENT')),
      assigned_by uuid references users (id) on delete restrict,
      created_at timestamptz not null default now(),
      primary key (user_id, role)
    );
    create index user_roles_assigned_by_idx on user_roles (assigned_by);

    create table sessions (
      token_hash text primary key,
      user_id uuid not null references users (id) on delete cascade,
      csrf_token text not null,
      created_at timestamptz not null default now(),
      last_seen_at timestamptz not null default now(),
      expires_at timestamptz not null
    );
    create index sessions_user_id_idx on sessions (user_id);

    create table classes (
      id uuid primary key default gen_random_uuid(),
      code text not null check (length(code) between 1 and 32),
      label text not null check (length(label) between 1 and 160),
      academic_year text not null check (academic_year ~ '^\\d{4}/\\d{4}$'),
      active boolean not null default true,
      unique (code, academic_year)
    );
    -- Import siswa me-resolve kolom "Kelas" lewat code kelas aktif: harus tunggal.
    create unique index classes_active_code_key on classes (code) where active;

    create table class_memberships (
      class_id uuid not null references classes (id) on delete restrict,
      student_id uuid not null references users (id) on delete restrict,
      created_at timestamptz not null default now(),
      primary key (student_id, class_id)
    );
    create index class_memberships_class_id_idx on class_memberships (class_id);

    create table subjects (
      id uuid primary key default gen_random_uuid(),
      code text not null unique check (length(code) between 1 and 32),
      name text not null check (length(name) between 1 and 160)
    );

    create table teaching_assignments (
      id uuid primary key default gen_random_uuid(),
      teacher_id uuid not null references users (id) on delete restrict,
      class_id uuid not null references classes (id) on delete restrict,
      subject_id uuid not null references subjects (id) on delete restrict,
      unique (teacher_id, class_id, subject_id)
    );
    create index teaching_assignments_class_id_idx on teaching_assignments (class_id);
    create index teaching_assignments_subject_id_idx on teaching_assignments (subject_id);

    create table import_jobs (
      id uuid primary key default gen_random_uuid(),
      type text not null check (type in ('STUDENT_XLSX')),
      created_by uuid not null references users (id) on delete restrict,
      status text not null check (status in ('PREVIEW', 'COMPLETED')),
      source_sha256 text not null,
      rows jsonb,
      errors jsonb not null default '[]',
      created_at timestamptz not null default now()
    );
    create index import_jobs_created_by_idx on import_jobs (created_by);
    """)


def downgrade() -> None:
    op.execute("""
    drop table import_jobs, teaching_assignments, subjects, class_memberships, classes,
      sessions, user_roles, users;
    """)
