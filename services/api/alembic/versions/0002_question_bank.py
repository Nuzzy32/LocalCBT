"""question bank: banks, shares, media, stimuli, questions, options, statements

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18

Catatan vs DATABASE_DESIGN §4: question_banks.visibility dihapus (selalu privat, akses lewat
bank_shares); media_assets.storage_key dihapus (path diturunkan dari sha256).
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    create table question_banks (
      id uuid primary key default gen_random_uuid(),
      owner_teacher_id uuid not null references users (id) on delete restrict,
      subject_id uuid not null references subjects (id) on delete restrict,
      title text not null check (length(title) between 1 and 160),
      created_at timestamptz not null default now()
    );
    create index question_banks_owner_idx on question_banks (owner_teacher_id);
    create index question_banks_subject_idx on question_banks (subject_id);

    create table bank_shares (
      bank_id uuid not null references question_banks (id) on delete restrict,
      teacher_id uuid not null references users (id) on delete restrict,
      permission text not null check (permission in ('VIEW', 'COPY', 'EDIT')),
      granted_by uuid not null references users (id) on delete restrict,
      created_at timestamptz not null default now(),
      primary key (bank_id, teacher_id)
    );
    create index bank_shares_teacher_idx on bank_shares (teacher_id);
    create index bank_shares_granted_by_idx on bank_shares (granted_by);

    create table media_assets (
      id uuid primary key default gen_random_uuid(),
      sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
      mime text not null check (mime in ('image/png', 'image/jpeg', 'image/webp')),
      size_bytes int not null check (size_bytes between 1 and 2097152),
      width int not null check (width > 0),
      height int not null check (height > 0),
      alt_text text check (length(alt_text) <= 300),
      created_by uuid not null references users (id) on delete restrict,
      created_at timestamptz not null default now(),
      unique (created_by, sha256)
    );

    create table stimuli (
      id uuid primary key default gen_random_uuid(),
      bank_id uuid not null references question_banks (id) on delete restrict,
      body_text text check (length(body_text) between 1 and 10000),
      media_asset_id uuid references media_assets (id) on delete restrict,
      created_at timestamptz not null default now(),
      check (body_text is not null or media_asset_id is not null),
      unique (bank_id, id)
    );
    create index stimuli_media_idx on stimuli (media_asset_id);

    create table questions (
      id uuid primary key default gen_random_uuid(),
      bank_id uuid not null references question_banks (id) on delete restrict,
      stimulus_id uuid,
      media_asset_id uuid references media_assets (id) on delete restrict,
      type text not null
        check (type in ('SINGLE_CHOICE', 'MULTIPLE_CHOICE', 'CATEGORY_CHOICE')),
      stem text not null check (length(stem) between 1 and 10000),
      weight numeric(8, 2) not null check (weight > 0),
      version int not null default 1,
      active boolean not null default true,
      created_by uuid not null references users (id) on delete restrict,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      -- Stimulus wajib dari bank yang sama (dijamin DB, bukan hanya app).
      foreign key (bank_id, stimulus_id) references stimuli (bank_id, id) on delete restrict
    );
    create index questions_bank_idx on questions (bank_id);
    create index questions_stimulus_idx on questions (stimulus_id);
    create index questions_media_idx on questions (media_asset_id);
    create index questions_created_by_idx on questions (created_by);

    create table question_options (
      id uuid primary key default gen_random_uuid(),
      question_id uuid not null references questions (id) on delete cascade,
      content text not null check (length(content) between 1 and 2000),
      sort_order smallint not null,
      is_correct boolean not null,
      unique (question_id, sort_order)
    );

    create table question_statements (
      id uuid primary key default gen_random_uuid(),
      question_id uuid not null references questions (id) on delete cascade,
      content text not null check (length(content) between 1 and 2000),
      sort_order smallint not null,
      correct_value boolean not null,
      unique (question_id, sort_order)
    );

    alter table import_jobs drop constraint import_jobs_type_check;
    alter table import_jobs add constraint import_jobs_type_check
      check (type in ('STUDENT_XLSX', 'QUESTION_XLSX', 'QUESTION_DOCX'));
    alter table import_jobs add column bank_id uuid references question_banks (id)
      on delete restrict;
    create index import_jobs_bank_idx on import_jobs (bank_id);
    """)


def downgrade() -> None:
    op.execute("""
    alter table import_jobs drop column bank_id;
    delete from import_jobs where type <> 'STUDENT_XLSX';
    alter table import_jobs drop constraint import_jobs_type_check;
    alter table import_jobs add constraint import_jobs_type_check
      check (type in ('STUDENT_XLSX'));
    drop table question_statements, question_options, questions, stimuli, media_assets,
      bank_shares, question_banks;
    """)
