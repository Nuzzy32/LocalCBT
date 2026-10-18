"""exams, class assignments, immutable question snapshots

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18

Catatan vs DATABASE_DESIGN §5: status hanya DRAFT/PUBLISHED; ACTIVE/CLOSED diturunkan dari waktu
server terhadap start window (ARCHIVED menyusul M8). exam_policy_versions diganti kolom
exams.scoring_rule_version. proctor_assignments menyusul M7.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    create table exams (
      id uuid primary key default gen_random_uuid(),
      author_teacher_id uuid not null references users (id) on delete restrict,
      subject_id uuid not null references subjects (id) on delete restrict,
      title text not null check (length(title) between 1 and 160),
      status text not null default 'DRAFT' check (status in ('DRAFT', 'PUBLISHED')),
      start_window_from timestamptz not null,
      start_window_until timestamptz not null,
      duration_sec int not null check (duration_sec between 60 and 86400),
      token_hash text not null,
      -- ponytail: pilihan soal draft tanpa FK; publish memvalidasi ulang. Tabel join bila perlu.
      question_ids uuid[] not null default '{}',
      result_visibility text not null default 'TEACHER_ONLY'
        check (result_visibility in ('TEACHER_ONLY', 'IMMEDIATE', 'AFTER_PUBLICATION')),
      review_policy jsonb not null default '{}',
      scoring_rule_version text check (scoring_rule_version in ('PROPOSED-1')),
      published_at timestamptz,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      check (start_window_until > start_window_from),
      check (status = 'DRAFT' or (published_at is not null and scoring_rule_version is not null))
    );
    create index exams_author_idx on exams (author_teacher_id);
    create index exams_subject_idx on exams (subject_id);
    create index exams_status_window_idx on exams (status, start_window_from, start_window_until);

    create table exam_assignments (
      exam_id uuid not null references exams (id) on delete restrict,
      class_id uuid not null references classes (id) on delete restrict,
      primary key (exam_id, class_id)
    );
    create index exam_assignments_class_idx on exam_assignments (class_id);

    create table exam_question_snapshots (
      id uuid primary key default gen_random_uuid(),
      exam_id uuid not null references exams (id) on delete restrict,
      source_question_id uuid not null references questions (id) on delete restrict,
      snapshot_version int not null,
      question_type text not null
        check (question_type in ('SINGLE_CHOICE', 'MULTIPLE_CHOICE', 'CATEGORY_CHOICE')),
      stem text not null,
      weight numeric(8, 2) not null check (weight > 0),
      -- FK nyata (bukan di jsonb): GC media tidak bisa menghapus gambar yang dipakai ujian.
      media_asset_id uuid references media_assets (id) on delete restrict,
      stimulus_media_asset_id uuid references media_assets (id) on delete restrict,
      stimulus_payload jsonb,
      options_payload jsonb not null,
      statements_payload jsonb not null,
      -- Kunci hanya di sini; endpoint siswa memakai whitelist to_student_question.
      answer_key jsonb not null,
      ordinal int not null,
      unique (exam_id, ordinal),
      unique (exam_id, source_question_id)
    );
    create index snapshots_source_idx on exam_question_snapshots (source_question_id);
    create index snapshots_media_idx on exam_question_snapshots (media_asset_id);
    create index snapshots_stimulus_media_idx
      on exam_question_snapshots (stimulus_media_asset_id);

    -- Snapshot ujian immutable di level DB (bukan hanya aplikasi).
    create function forbid_snapshot_update() returns trigger language plpgsql as $$
    begin
      raise exception 'exam_question_snapshots bersifat immutable';
    end $$;
    create trigger exam_question_snapshots_immutable
      before update on exam_question_snapshots
      for each row execute function forbid_snapshot_update();
    """)


def downgrade() -> None:
    op.execute("""
    drop table exam_question_snapshots, exam_assignments, exams;
    drop function forbid_snapshot_update();
    """)
