"""attempts, answers, per-question scores

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18

Catatan vs DATABASE_DESIGN §6:
- attempt_question_orders → kolom jsonb exam_attempts.question_order (ditulis sekali saat mulai).
- exam_results → kolom skor di exam_attempts (1:1); satu baris attempt = mustahil dua hasil.
- idempotency_records belum dibutuhkan: simpan jawaban & submit idempotent lewat kunci/state.
- Batas waktu tunggal effective_deadline_at; M6 (jeda) & M7 (tambah waktu) memperbaruinya
  dalam transaksi yang sama dengan pencatatan insiden/perpanjangan.
- Publikasi nilai per ujian: exams.results_published_at.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    alter table exams add column results_published_at timestamptz;

    create table exam_attempts (
      id uuid primary key default gen_random_uuid(),
      exam_id uuid not null references exams (id) on delete restrict,
      student_id uuid not null references users (id) on delete restrict,
      state text not null default 'IN_PROGRESS'
        check (state in ('IN_PROGRESS', 'PAUSED', 'SUBMITTED', 'GRADED')),
      started_at timestamptz not null default now(),
      effective_deadline_at timestamptz not null,
      randomization_seed bigint not null,
      question_order jsonb not null,
      submitted_at timestamptz,
      submit_reason text check (submit_reason in ('STUDENT', 'DEADLINE')),
      graded_at timestamptz,
      score_total numeric(10, 2),
      score_max numeric(10, 2),
      grading_version text,
      unique (exam_id, student_id),
      check ((state in ('IN_PROGRESS', 'PAUSED')) = (submitted_at is null)),
      check ((state = 'GRADED') = (graded_at is not null))
    );
    create index exam_attempts_student_idx on exam_attempts (student_id);
    create index exam_attempts_exam_state_idx on exam_attempts (exam_id, state);

    create table student_answers (
      attempt_id uuid not null references exam_attempts (id) on delete restrict,
      snapshot_question_id uuid not null
        references exam_question_snapshots (id) on delete restrict,
      answer jsonb,
      marked boolean not null default false,
      server_revision int not null check (server_revision >= 1),
      client_revision int not null,
      saved_at timestamptz not null default now(),
      idempotency_key uuid not null,
      primary key (attempt_id, snapshot_question_id)
    );
    create index student_answers_snapshot_idx on student_answers (snapshot_question_id);

    create table question_scores (
      attempt_id uuid not null references exam_attempts (id) on delete restrict,
      snapshot_question_id uuid not null
        references exam_question_snapshots (id) on delete restrict,
      earned numeric(8, 2) not null check (earned >= 0),
      max_score numeric(8, 2) not null,
      check (earned <= max_score),
      primary key (attempt_id, snapshot_question_id)
    );
    create index question_scores_snapshot_idx on question_scores (snapshot_question_id);
    """)


def downgrade() -> None:
    op.execute("""
    drop table question_scores, student_answers, exam_attempts;
    alter table exams drop column results_published_at;
    """)
