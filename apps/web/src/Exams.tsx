import { type FormEvent, useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
	type Question,
	type StudentQuestion,
	StudentQuestionView,
	TYPE_LABEL,
} from "./QuestionEditor";
import { ExamResults } from "./Results";
import { ActionForm, Alert, Field, message, navigate } from "./ui";

type Visibility = "TEACHER_ONLY" | "IMMEDIATE" | "AFTER_PUBLICATION";
type Policy = {
	visibility: Visibility;
	review_enabled: boolean;
	review_available_from: string | null;
	show_correct_answers: boolean;
};
type Exam = {
	id: string;
	title: string;
	subject_id: string;
	subject_name: string;
	status: "DRAFT" | "PUBLISHED" | "ACTIVE" | "CLOSED";
	start_window_from: string;
	start_window_until: string;
	duration_seconds: number;
	class_ids: string[];
	class_names: string;
	question_ids: string[];
	question_count: number;
	result_policy: Policy;
	scoring_rule_version: string | null;
	scoring_rule?: { version: string; text: string };
};
type Bank = { id: string; title: string; subject_id: string; access: string };
type Option = { id: string; name: string };

const STATUS_LABEL: Record<Exam["status"], string> = {
	DRAFT: "Draft",
	PUBLISHED: "Terjadwal",
	ACTIVE: "Berlangsung",
	CLOSED: "Selesai",
};
const VISIBILITY_LABEL: Record<Visibility, string> = {
	TEACHER_ONLY: "Hanya guru (default)",
	IMMEDIATE: "Langsung setelah siswa mengumpulkan",
	AFTER_PUBLICATION: "Setelah guru mempublikasikan nilai",
};
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
const fmt = (iso: string) =>
	new Date(iso).toLocaleString("id-ID", {
		dateStyle: "medium",
		timeStyle: "short",
	});
// ISO (UTC) ↔ nilai <input type="datetime-local"> di zona waktu perangkat.
const toLocalInput = (iso: string) => {
	const d = new Date(iso);
	return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
		.toISOString()
		.slice(0, 16);
};
const fromLocalInput = (v: string) => new Date(v).toISOString();
// Di state UI, review_available_from disimpan dalam format datetime-local.
const policyFromApi = (p: Policy): Policy => ({
	...p,
	review_available_from:
		p.review_available_from && toLocalInput(p.review_available_from),
});
const policyToApi = (p: Policy): Policy => ({
	...p,
	review_available_from:
		p.review_available_from && fromLocalInput(p.review_available_from),
});

export function ExamsPage({ path }: { path: string }) {
	const [, , , id, sub] = path.split("/");
	if (id === "new") return <ExamBuilder exam={null} />;
	if (id && sub === "preview") return <ExamPreview examId={id} />;
	if (id && sub === "results") return <ExamResults examId={id} />;
	if (id) return <ExamDetail key={id} examId={id} />;
	return <ExamList />;
}

function ExamList() {
	const [exams, setExams] = useState<Exam[] | null>(null);
	const [error, setError] = useState("");
	useEffect(() => {
		api<Exam[]>("/exams")
			.then(setExams)
			.catch((err) => setError(message(err)));
	}, []);
	return (
		<div className="stack-lg">
			<div>
				<button
					type="button"
					className="btn btn-primary"
					onClick={() => navigate("/teacher/exams/new")}
				>
					Buat ujian
				</button>
			</div>
			<Alert kind="error">{error}</Alert>
			{exams?.length === 0 && (
				<p className="muted">
					Belum ada ujian. Buat ujian dari bank soal Anda.
				</p>
			)}
			{exams && exams.length > 0 && (
				<ul className="question-list">
					{exams.map((e) => (
						<li key={e.id} className="card">
							<div className="stack">
								<strong>{e.title}</strong>
								<p className="muted">
									<span className={`chip chip-${e.status.toLowerCase()}`}>
										{STATUS_LABEL[e.status]}
									</span>{" "}
									{e.subject_name} · {e.class_names || "tanpa kelas"} ·{" "}
									{e.question_count} soal · {e.duration_seconds / 60} menit
								</p>
								<p className="muted">
									Mulai {fmt(e.start_window_from)} – {fmt(e.start_window_until)}
								</p>
							</div>
							<div className="row-actions">
								<button
									type="button"
									className="btn btn-secondary"
									onClick={() => navigate(`/teacher/exams/${e.id}`)}
								>
									{e.status === "DRAFT" ? "Edit" : "Detail"}
								</button>
							</div>
						</li>
					))}
				</ul>
			)}
		</div>
	);
}

type Draft = {
	title: string;
	subject_id: string;
	class_ids: string[];
	question_ids: string[];
	from: string;
	until: string;
	minutes: string;
	token: string;
	policy: Policy;
};

function ExamBuilder({ exam }: { exam: Exam | null }) {
	const [d, setD] = useState<Draft>(() => ({
		title: exam?.title ?? "",
		subject_id: exam?.subject_id ?? "",
		class_ids: exam?.class_ids ?? [],
		question_ids: exam?.question_ids ?? [],
		from: exam ? toLocalInput(exam.start_window_from) : "",
		until: exam ? toLocalInput(exam.start_window_until) : "",
		minutes: exam ? String(exam.duration_seconds / 60) : "90",
		token: "",
		policy: exam
			? policyFromApi(exam.result_policy)
			: {
					visibility: "TEACHER_ONLY",
					review_enabled: false,
					review_available_from: null,
					show_correct_answers: false,
				},
	}));
	const [subjects, setSubjects] = useState<Option[]>([]);
	const [classes, setClasses] = useState<Option[]>([]);
	const [banks, setBanks] = useState<Bank[]>([]);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const update = (patch: Partial<Draft>) => setD((p) => ({ ...p, ...patch }));
	const toggle = (list: string[], id: string) =>
		list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

	useEffect(() => {
		Promise.all([
			api<Option[]>("/admin/subjects"),
			api<{ id: string; code: string; label: string }[]>("/admin/classes"),
			api<Bank[]>("/question-banks"),
		])
			.then(([s, c, b]) => {
				setSubjects(s);
				setClasses(
					c.map((k) => ({ id: k.id, name: `${k.code} · ${k.label}` })),
				);
				setBanks(b);
			})
			.catch((err) => setError(message(err)));
	}, []);

	async function save(e: FormEvent) {
		e.preventDefault();
		setBusy(true);
		setError("");
		try {
			const body = {
				title: d.title,
				subject_id: d.subject_id,
				class_ids: d.class_ids,
				question_ids: d.question_ids,
				start_window_from: d.from && fromLocalInput(d.from),
				start_window_until: d.until && fromLocalInput(d.until),
				duration_seconds: Math.round(Number(d.minutes) * 60),
				token: d.token || null,
				result_policy: policyToApi(d.policy),
			};
			const saved = await api<Exam>(exam ? `/exams/${exam.id}` : "/exams", {
				method: exam ? "PUT" : "POST",
				json: body,
			});
			navigate(`/teacher/exams/${saved.id}`);
		} catch (err) {
			setError(message(err));
			setBusy(false);
		}
	}

	const usableBanks = banks.filter(
		(b) =>
			b.subject_id === d.subject_id &&
			["OWNER", "EDIT", "COPY"].includes(b.access),
	);

	return (
		<form onSubmit={save} className="stack-lg" noValidate>
			<section className="card stack" aria-labelledby="h-basic">
				<h2 id="h-basic">{exam ? "Edit ujian" : "Ujian baru"}</h2>
				<div className="form-row">
					<Field
						label="Judul"
						value={d.title}
						maxLength={160}
						onChange={(e) => update({ title: e.target.value })}
					/>
					<label className="field">
						<span>Mata pelajaran</span>
						<select
							value={d.subject_id}
							required
							onChange={(e) =>
								update({ subject_id: e.target.value, question_ids: [] })
							}
						>
							<option value="" disabled>
								Pilih…
							</option>
							{subjects.map((s) => (
								<option key={s.id} value={s.id}>
									{s.name}
								</option>
							))}
						</select>
					</label>
				</div>
				<fieldset className="stack">
					<legend>Kelas peserta (hanya kelas yang Anda ajar)</legend>
					{classes.length === 0 && (
						<p className="muted">
							Belum ada kelas yang ditugaskan kepada Anda.
						</p>
					)}
					<div className="form-row">
						{classes.map((c) => (
							<label key={c.id} className="check">
								<input
									type="checkbox"
									checked={d.class_ids.includes(c.id)}
									onChange={() =>
										update({ class_ids: toggle(d.class_ids, c.id) })
									}
								/>
								{c.name}
							</label>
						))}
					</div>
				</fieldset>
			</section>

			<section className="card stack" aria-labelledby="h-time">
				<h2 id="h-time">Jadwal & akses</h2>
				<p className="muted">
					Siswa boleh mulai di antara dua waktu ini; durasi dihitung per siswa
					sejak ia mulai. Zona waktu: {TZ}.
				</p>
				<div className="form-row">
					<Field
						label="Mulai dibuka"
						type="datetime-local"
						value={d.from}
						onChange={(e) => update({ from: e.target.value })}
					/>
					<Field
						label="Batas akhir mulai"
						type="datetime-local"
						value={d.until}
						onChange={(e) => update({ until: e.target.value })}
					/>
					<Field
						label="Durasi (menit)"
						inputMode="numeric"
						value={d.minutes}
						onChange={(e) => update({ minutes: e.target.value })}
					/>
					<Field
						label={exam ? "Token baru (kosongkan bila tetap)" : "Token ujian"}
						type="password"
						autoComplete="off"
						minLength={4}
						maxLength={32}
						required={!exam}
						value={d.token}
						onChange={(e) => update({ token: e.target.value })}
					/>
				</div>
				<p className="muted">Urutan soal dan opsi selalu diacak per siswa.</p>
			</section>

			<PolicyFields
				policy={d.policy}
				onChange={(policy) => update({ policy })}
			/>

			<section className="card stack" aria-labelledby="h-pick">
				<h2 id="h-pick">Soal ({d.question_ids.length} dipilih)</h2>
				{!d.subject_id ? (
					<p className="muted">Pilih mata pelajaran dulu.</p>
				) : usableBanks.length === 0 ? (
					<p className="muted">
						Tidak ada bank soal mapel ini yang boleh Anda pakai (milik sendiri
						atau dibagikan dengan akses salin/edit).
					</p>
				) : (
					usableBanks.map((b) => (
						<BankPicker
							key={b.id}
							bank={b}
							selected={d.question_ids}
							onToggle={(id) =>
								update({ question_ids: toggle(d.question_ids, id) })
							}
						/>
					))
				)}
			</section>

			<Alert kind="error">{error}</Alert>
			<div className="form-row">
				<button type="submit" className="btn btn-primary" disabled={busy}>
					{busy ? "Menyimpan…" : "Simpan draft"}
				</button>
				<button
					type="button"
					className="btn btn-ghost"
					onClick={() =>
						navigate(exam ? `/teacher/exams/${exam.id}` : "/teacher/exams")
					}
				>
					Batal
				</button>
			</div>
		</form>
	);
}

function BankPicker({
	bank,
	selected,
	onToggle,
}: {
	bank: Bank;
	selected: string[];
	onToggle: (id: string) => void;
}) {
	const [questions, setQuestions] = useState<Question[] | null>(null);
	const [error, setError] = useState("");
	return (
		<details
			className="picker"
			onToggle={(e) => {
				if ((e.currentTarget as HTMLDetailsElement).open && !questions) {
					api<Question[]>(`/question-banks/${bank.id}/questions`)
						.then(setQuestions)
						.catch((err) => setError(message(err)));
				}
			}}
		>
			<summary>{bank.title}</summary>
			<Alert kind="error">{error}</Alert>
			{questions?.length === 0 && (
				<p className="muted">Bank ini belum berisi soal.</p>
			)}
			{questions?.map((q) => (
				<label key={q.id} className="check pick-row">
					<input
						type="checkbox"
						checked={selected.includes(q.id)}
						onChange={() => onToggle(q.id)}
					/>
					<span>
						<span className="muted">
							{TYPE_LABEL[q.type]} · bobot {q.weight}
							{q.stimulus_id && " · stimulus"}
						</span>
						<br />
						{q.stem.slice(0, 140)}
					</span>
				</label>
			))}
		</details>
	);
}

function PolicyFields({
	policy,
	onChange,
}: {
	policy: Policy;
	onChange: (p: Policy) => void;
}) {
	const set = (patch: Partial<Policy>) => onChange({ ...policy, ...patch });
	return (
		<section className="card stack" aria-labelledby="h-policy">
			<h2 id="h-policy">Nilai & pembahasan</h2>
			<fieldset className="stack">
				<legend>Kapan siswa melihat nilai</legend>
				{(Object.keys(VISIBILITY_LABEL) as Visibility[]).map((v) => (
					<label key={v} className="check">
						<input
							type="radio"
							name="visibility"
							checked={policy.visibility === v}
							onChange={() => set({ visibility: v })}
						/>
						{VISIBILITY_LABEL[v]}
					</label>
				))}
			</fieldset>
			<label className="check">
				<input
					type="checkbox"
					checked={policy.review_enabled}
					onChange={(e) => set({ review_enabled: e.target.checked })}
				/>
				Buka pembahasan (soal dan jawaban sendiri) untuk siswa
			</label>
			{policy.review_enabled && (
				<div className="form-row">
					<Field
						label="Pembahasan dibuka mulai"
						type="datetime-local"
						required={false}
						value={policy.review_available_from ?? ""}
						onChange={(e) =>
							set({ review_available_from: e.target.value || null })
						}
					/>
					<label className="check">
						<input
							type="checkbox"
							checked={policy.show_correct_answers}
							onChange={(e) => set({ show_correct_answers: e.target.checked })}
						/>
						Tampilkan kunci jawaban
					</label>
				</div>
			)}
		</section>
	);
}

function ExamDetail({ examId }: { examId: string }) {
	const [exam, setExam] = useState<Exam | null>(null);
	const [error, setError] = useState("");
	const [notice, setNotice] = useState("");
	const dialog = useRef<HTMLDialogElement>(null);
	const reload = () =>
		api<Exam>(`/exams/${examId}`)
			.then(setExam)
			.catch((err) => setError(message(err)));
	// biome-ignore lint/correctness/useExhaustiveDependencies: muat sekali per examId (key)
	useEffect(() => {
		reload();
	}, []);

	if (!exam) {
		return error ? (
			<Alert kind="error">{error}</Alert>
		) : (
			<p className="muted">Memuat…</p>
		);
	}
	if (exam.status === "DRAFT") {
		return (
			<div className="stack-lg">
				<div className="card stack">
					<h2>Siap dipublish?</h2>
					<p className="muted">
						Setelah publish, soal dibekukan: perubahan bank soal tidak
						memengaruhi ujian ini. Jadwal, kelas, dan soal tidak bisa diubah
						lagi (kecuali ditarik sebelum jadwal dibuka).
					</p>
					<div className="form-row">
						<button
							type="button"
							className="btn btn-secondary"
							onClick={() => navigate(`/teacher/exams/${exam.id}/preview`)}
						>
							Pratinjau & validasi
						</button>
						<button
							type="button"
							className="btn btn-primary"
							onClick={() => dialog.current?.showModal()}
						>
							Publish…
						</button>
					</div>
					<Alert kind="error">{error}</Alert>
				</div>
				<PublishDialog
					ref={dialog}
					exam={exam}
					onPublished={(e) => {
						setExam(e);
						setNotice("Ujian dipublish dan soal sudah dibekukan.");
					}}
				/>
				<ExamBuilder exam={exam} />
			</div>
		);
	}

	return (
		<div className="stack-lg">
			<Alert kind="success">{notice}</Alert>
			<section className="card stack" aria-labelledby="h-exam">
				<h2 id="h-exam">{exam.title}</h2>
				<p className="muted">
					<span className={`chip chip-${exam.status.toLowerCase()}`}>
						{STATUS_LABEL[exam.status]}
					</span>{" "}
					{exam.subject_name} · {exam.class_names} · {exam.question_count} soal
					· {exam.duration_seconds / 60} menit
				</p>
				<p className="muted">
					Mulai {fmt(exam.start_window_from)} – {fmt(exam.start_window_until)} ·
					aturan nilai {exam.scoring_rule_version} (belum disahkan sekolah)
				</p>
				<div className="form-row">
					<button
						type="button"
						className="btn btn-primary"
						onClick={() => navigate(`/proctor/exams/${exam.id}`)}
					>
						Pantau
					</button>
					<button
						type="button"
						className="btn btn-secondary"
						onClick={() => navigate(`/teacher/exams/${exam.id}/results`)}
					>
						Hasil & nilai
					</button>
					<button
						type="button"
						className="btn btn-secondary"
						onClick={() => navigate(`/teacher/exams/${exam.id}/preview`)}
					>
						Pratinjau acak
					</button>
					{exam.status === "PUBLISHED" && (
						<button
							type="button"
							className="btn btn-ghost danger"
							onClick={async () => {
								if (!window.confirm("Tarik ujian kembali menjadi draft?"))
									return;
								try {
									setExam(
										await api<Exam>(`/exams/${exam.id}/unpublish`, {
											method: "POST",
										}),
									);
								} catch (err) {
									setError(message(err));
								}
							}}
						>
							Tarik ke draft
						</button>
					)}
				</div>
				<Alert kind="error">{error}</Alert>
			</section>

			<section className="card stack" aria-labelledby="h-token">
				<h2 id="h-token">Ganti token</h2>
				<p className="muted">
					Token tidak pernah ditampilkan ulang. Ganti bila token bocor; siswa
					yang sudah mulai tidak terpengaruh.
				</p>
				<ActionForm
					label="Ganti token"
					run={async (f) => {
						await api(`/exams/${exam.id}/token`, {
							method: "PUT",
							json: { token: f.get("token") },
						});
						return "Token diganti.";
					}}
				>
					<Field
						label="Token baru"
						name="token"
						type="password"
						autoComplete="off"
						minLength={4}
						maxLength={32}
					/>
				</ActionForm>
			</section>

			<ProctorAssignments examId={exam.id} />
			<PolicyEditor exam={exam} />
		</div>
	);
}

function PolicyEditor({ exam }: { exam: Exam }) {
	const [policy, setPolicy] = useState(() => policyFromApi(exam.result_policy));
	const [busy, setBusy] = useState(false);
	const [result, setResult] = useState<{
		kind: "error" | "success";
		text: string;
	}>();
	return (
		<div className="stack">
			<PolicyFields policy={policy} onChange={setPolicy} />
			{result && <Alert kind={result.kind}>{result.text}</Alert>}
			<div>
				<button
					type="button"
					className="btn btn-primary"
					disabled={busy}
					onClick={async () => {
						setBusy(true);
						try {
							await api(`/teacher/exams/${exam.id}/result-policy`, {
								method: "PUT",
								json: policyToApi(policy),
							});
							setResult({ kind: "success", text: "Kebijakan nilai disimpan." });
						} catch (err) {
							setResult({ kind: "error", text: message(err) });
						} finally {
							setBusy(false);
						}
					}}
				>
					Simpan kebijakan nilai
				</button>
			</div>
		</div>
	);
}

function PublishDialog({
	ref,
	exam,
	onPublished,
}: {
	ref: React.Ref<HTMLDialogElement>;
	exam: Exam;
	onPublished: (e: Exam) => void;
}) {
	const [agreed, setAgreed] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const rule = exam.scoring_rule;

	async function publish(e: FormEvent<HTMLFormElement>) {
		e.preventDefault();
		const dialog = e.currentTarget.closest("dialog");
		setBusy(true);
		setError("");
		try {
			const published = await api<Exam>(`/exams/${exam.id}/publish`, {
				json: { confirm: true, scoring_rule_version: rule?.version },
			});
			dialog?.close();
			onPublished(published);
		} catch (err) {
			setError(message(err));
		} finally {
			setBusy(false);
		}
	}

	return (
		<dialog ref={ref} className="dialog" aria-labelledby="h-publish">
			<form onSubmit={publish} className="stack">
				<h2 id="h-publish">Publish “{exam.title}”</h2>
				<p>{rule?.text}</p>
				<label className="check">
					<input
						type="checkbox"
						checked={agreed}
						onChange={(e) => setAgreed(e.target.checked)}
					/>
					Saya menyetujui aturan penilaian {rule?.version} untuk ujian ini
				</label>
				<Alert kind="error">{error}</Alert>
				<div className="form-row">
					<button
						type="submit"
						className="btn btn-primary"
						disabled={!agreed || busy}
					>
						{busy ? "Mempublish…" : "Publish & bekukan soal"}
					</button>
					<button
						type="button"
						className="btn btn-ghost"
						onClick={(e) => e.currentTarget.closest("dialog")?.close()}
					>
						Batal
					</button>
				</div>
			</form>
		</dialog>
	);
}

function ExamPreview({ examId }: { examId: string }) {
	const [data, setData] = useState<{
		questions: StudentQuestion[];
		validation_errors: string[];
	} | null>(null);
	const [error, setError] = useState("");
	const load = () =>
		api<typeof data>(`/teacher/exams/${examId}/preview`)
			.then(setData)
			.catch((err) => setError(message(err)));
	// biome-ignore lint/correctness/useExhaustiveDependencies: muat sekali saat dibuka
	useEffect(() => {
		load();
	}, []);
	return (
		<section className="stack" aria-labelledby="h-exam-preview">
			<div>
				<button
					type="button"
					className="btn btn-ghost"
					onClick={() => navigate(`/teacher/exams/${examId}`)}
				>
					← Kembali ke ujian
				</button>
			</div>
			<h2 id="h-exam-preview">Pratinjau seperti satu peserta</h2>
			<p className="muted">
				Contoh urutan acak; setiap siswa mendapat urutan soal dan opsi yang
				berbeda. Soal dengan stimulus sama tetap berdampingan.
			</p>
			<div>
				<button type="button" className="btn btn-secondary" onClick={load}>
					Acak ulang
				</button>
			</div>
			<Alert kind="error">{error}</Alert>
			{data?.validation_errors.map((e) => (
				<Alert key={e} kind="warning">
					{e}
				</Alert>
			))}
			<div className="reading stack">
				{data?.questions.map((q, i) => (
					<StudentQuestionView
						key={q.id}
						q={q}
						number={i + 1}
						total={data.questions.length}
					/>
				))}
			</div>
		</section>
	);
}

type Person = { id: string; display_name: string };

function ProctorAssignments({ examId }: { examId: string }) {
	const [data, setData] = useState<{
		assigned: Person[];
		candidates: Person[];
	}>();
	const [pick, setPick] = useState("");
	const [error, setError] = useState("");
	const load = () =>
		api<{ assigned: Person[]; candidates: Person[] }>(
			`/exams/${examId}/proctors`,
		)
			.then(setData)
			.catch((err) => setError(message(err)));
	// biome-ignore lint/correctness/useExhaustiveDependencies: muat sekali per ujian
	useEffect(() => {
		load();
	}, [examId]);

	async function change(method: "POST" | "DELETE", userId: string) {
		setError("");
		try {
			await api(
				method === "POST"
					? `/exams/${examId}/proctors`
					: `/exams/${examId}/proctors/${userId}`,
				{ method, json: method === "POST" ? { user_id: userId } : undefined },
			);
			setPick("");
			load();
		} catch (err) {
			setError(message(err));
		}
	}

	const assignedIds = new Set(data?.assigned.map((p) => p.id));
	return (
		<section className="card stack" aria-labelledby="h-proctors">
			<h2 id="h-proctors">Pengawas</h2>
			<p className="muted">
				Anda selalu bisa mengawasi ujian sendiri. Pengawas yang ditugaskan hanya
				melihat ujian ini, tanpa kunci jawaban maupun nilai.
			</p>
			<Alert kind="error">{error}</Alert>
			{data?.assigned.length ? (
				<ul className="list">
					{data.assigned.map((p) => (
						<li key={p.id}>
							<span>{p.display_name}</span>
							<button
								type="button"
								className="btn btn-ghost danger"
								onClick={() => change("DELETE", p.id)}
							>
								Lepas
							</button>
						</li>
					))}
				</ul>
			) : (
				<p className="muted">Belum ada pengawas tambahan.</p>
			)}
			<div className="form-row">
				<label className="field">
					<span>Tugaskan pengawas</span>
					<select value={pick} onChange={(e) => setPick(e.target.value)}>
						<option value="">Pilih…</option>
						{data?.candidates
							.filter((c) => !assignedIds.has(c.id))
							.map((c) => (
								<option key={c.id} value={c.id}>
									{c.display_name}
								</option>
							))}
					</select>
				</label>
				<button
					type="button"
					className="btn btn-secondary"
					disabled={!pick}
					onClick={() => change("POST", pick)}
				>
					Tugaskan
				</button>
			</div>
		</section>
	);
}
