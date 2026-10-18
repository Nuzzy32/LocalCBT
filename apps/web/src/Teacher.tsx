import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ExamsPage } from "./Exams";
import {
	type Question,
	QuestionEditor,
	type Stimulus,
	type StudentQuestion,
	StudentQuestionView,
	TYPE_LABEL,
} from "./QuestionEditor";
import {
	ActionForm,
	Alert,
	Field,
	ImportPanel,
	message,
	navigate,
	Select,
} from "./ui";

type Access = "VIEW" | "COPY" | "EDIT" | "OWNER";
type Bank = {
	id: string;
	title: string;
	subject_name: string;
	owner_name?: string;
	access: Access;
	question_count?: number;
};
const LEVEL: Record<Access, number> = { VIEW: 1, COPY: 2, EDIT: 3, OWNER: 4 };
const ACCESS_LABEL: Record<Access, string> = {
	VIEW: "Lihat",
	COPY: "Lihat & salin",
	EDIT: "Edit",
	OWNER: "Pemilik",
};

export function TeacherPage({ path }: { path: string }) {
	const onExams = path.startsWith("/teacher/exams");
	const bankId = path.match(/^\/teacher\/questions\/([0-9a-f-]{36})$/)?.[1];
	return (
		<div className="stack-lg">
			<nav className="tabs" aria-label="Menu guru">
				<a
					href="/teacher/questions"
					aria-current={onExams ? undefined : "page"}
					onClick={(e) => {
						e.preventDefault();
						navigate("/teacher/questions");
					}}
				>
					Bank soal
				</a>
				<a
					href="/teacher/exams"
					aria-current={onExams ? "page" : undefined}
					onClick={(e) => {
						e.preventDefault();
						navigate("/teacher/exams");
					}}
				>
					Ujian
				</a>
			</nav>
			{onExams ? (
				<ExamsPage path={path} />
			) : bankId ? (
				<BankDetail key={bankId} bankId={bankId} />
			) : (
				<BankList />
			)}
		</div>
	);
}

function BankList() {
	const [banks, setBanks] = useState<Bank[] | null>(null);
	const [subjects, setSubjects] = useState<{ id: string; name: string }[]>([]);
	const [error, setError] = useState("");

	useEffect(() => {
		Promise.all([
			api<Bank[]>("/question-banks"),
			api<{ id: string; name: string }[]>("/admin/subjects"),
		])
			.then(([b, s]) => {
				setBanks(b);
				setSubjects(s);
			})
			.catch((err) => setError(message(err)));
	}, []);

	const section = (title: string, list: Bank[], empty: string) => (
		<section className="card stack" aria-label={title}>
			<h2>{title}</h2>
			{list.length === 0 ? (
				<p className="muted">{empty}</p>
			) : (
				<ul className="list">
					{list.map((b) => (
						<li key={b.id}>
							<div>
								<strong>{b.title}</strong>
								<p className="muted">
									{b.subject_name} · {b.question_count} soal
									{b.access !== "OWNER" &&
										` · dari ${b.owner_name} · akses ${ACCESS_LABEL[b.access]}`}
								</p>
							</div>
							<button
								type="button"
								className="btn btn-secondary"
								onClick={() => navigate(`/teacher/questions/${b.id}`)}
							>
								Buka
							</button>
						</li>
					))}
				</ul>
			)}
		</section>
	);

	return (
		<div className="stack-lg">
			<Alert kind="error">{error}</Alert>
			{banks === null ? (
				!error && <p className="muted">Memuat bank soal…</p>
			) : (
				<>
					{section(
						"Bank soal saya",
						banks.filter((b) => b.access === "OWNER"),
						"Belum ada bank soal. Buat bank pertama di bawah.",
					)}
					{section(
						"Dibagikan kepada saya",
						banks.filter((b) => b.access !== "OWNER"),
						"Belum ada bank soal yang dibagikan guru lain.",
					)}
				</>
			)}
			<section className="card stack" aria-labelledby="h-new-bank">
				<h2 id="h-new-bank">Bank soal baru</h2>
				{subjects.length === 0 ? (
					<p className="muted">
						Belum ada mata pelajaran. Minta admin menambahkannya.
					</p>
				) : (
					<ActionForm
						label="Buat bank"
						run={async (f) => {
							const bank = await api<Bank>("/question-banks", {
								json: {
									title: f.get("title"),
									subject_id: f.get("subject_id"),
								},
							});
							navigate(`/teacher/questions/${bank.id}`);
							return undefined;
						}}
					>
						<Field label="Judul" name="title" maxLength={160} />
						<Select
							label="Mata pelajaran"
							name="subject_id"
							options={subjects.map((s) => ({ value: s.id, label: s.name }))}
						/>
					</ActionForm>
				)}
			</section>
		</div>
	);
}

type View = "list" | "edit" | "import" | "preview" | "share" | "copy";

function BankDetail({ bankId }: { bankId: string }) {
	const [bank, setBank] = useState<Bank | null>(null);
	const [questions, setQuestions] = useState<Question[]>([]);
	const [stimuli, setStimuli] = useState<Stimulus[]>([]);
	const [view, setView] = useState<View>("list");
	const [editing, setEditing] = useState<Question | null>(null);
	const [error, setError] = useState("");
	const base = `/question-banks/${bankId}`;

	const reload = useCallback(() => {
		Promise.all([
			api<Bank>(base),
			api<Question[]>(`${base}/questions`),
			api<Stimulus[]>(`${base}/stimuli`),
		])
			.then(([b, q, s]) => {
				setBank(b);
				setQuestions(q);
				setStimuli(s);
			})
			.catch((err) => setError(message(err)));
	}, [base]);
	useEffect(reload, [reload]);

	if (!bank) {
		return (
			<div className="stack">
				<Alert kind="error">{error}</Alert>
				{!error && <p className="muted">Memuat…</p>}
				<BackLink />
			</div>
		);
	}

	const can = (need: Access) => LEVEL[bank.access] >= LEVEL[need];
	const open = (v: View) => {
		setEditing(null);
		setView(view === v ? "list" : v);
	};
	const done = () => {
		setView("list");
		setEditing(null);
		reload();
	};

	async function remove(q: Question) {
		if (
			!window.confirm(
				"Hapus soal ini dari bank? Ujian yang sudah dipublish tidak berubah.",
			)
		) {
			return;
		}
		try {
			await api(`${base}/questions/${q.id}`, { method: "DELETE" });
			reload();
		} catch (err) {
			setError(message(err));
		}
	}

	return (
		<div className="stack-lg">
			<div className="stack">
				<BackLink />
				<h2 className="h1">{bank.title}</h2>
				<p className="muted">
					{bank.subject_name} · {questions.length} soal · akses{" "}
					{ACCESS_LABEL[bank.access]}
				</p>
				<div className="form-row" role="toolbar" aria-label="Aksi bank soal">
					{can("EDIT") && (
						<button
							type="button"
							className="btn btn-primary"
							onClick={() => {
								setEditing(null);
								setView("edit");
							}}
						>
							Tambah soal
						</button>
					)}
					{can("EDIT") && (
						<ToggleButton
							active={view === "import"}
							onClick={() => open("import")}
						>
							Import
						</ToggleButton>
					)}
					<ToggleButton
						active={view === "preview"}
						onClick={() => open("preview")}
					>
						Pratinjau siswa
					</ToggleButton>
					{can("COPY") && (
						<ToggleButton active={view === "copy"} onClick={() => open("copy")}>
							Salin ke bank lain
						</ToggleButton>
					)}
					{can("OWNER") && (
						<ToggleButton
							active={view === "share"}
							onClick={() => open("share")}
						>
							Bagikan
						</ToggleButton>
					)}
				</div>
				<Alert kind="error">{error}</Alert>
			</div>

			{view === "edit" && (
				<QuestionEditor
					key={editing?.id ?? "new"}
					bankId={bankId}
					stimuli={stimuli}
					initial={editing}
					onSaved={done}
					onCancel={() => setView("list")}
				/>
			)}
			{view === "import" && (
				<section className="card stack" aria-labelledby="h-import">
					<h2 id="h-import">Import soal</h2>
					<ImportPanel<{ imported: number }>
						previewPath={`${base}/imports/preview`}
						commitPath={`${base}/imports/commit`}
						accept=".xlsx,.docx"
						fileLabel="Berkas XLSX atau DOCX"
						rowLabel="soal"
						help={
							<p className="muted">
								Unduh template{" "}
								<a href="/api/v1/question-import-templates/xlsx" download>
									XLSX
								</a>{" "}
								(satu baris = satu soal) atau{" "}
								<a href="/api/v1/question-import-templates/docx" download>
									DOCX
								</a>{" "}
								(satu tabel = satu soal). Jenis: PG, MCMA, KATEGORI. Kunci:
								huruf opsi (mis. B atau A,C), atau B/S per pernyataan untuk
								KATEGORI. Stimulus yang teksnya sama dikelompokkan. Gambar
								ditambahkan lewat editor setelah import.
							</p>
						}
						onCommitted={({ imported }) => {
							reload();
							return (
								<Alert kind="success">{imported} soal berhasil diimport.</Alert>
							);
						}}
					/>
				</section>
			)}
			{view === "preview" && <BankPreview base={base} />}
			{view === "copy" && <CopyPanel base={base} currentId={bankId} />}
			{view === "share" && <SharePanel base={base} />}

			<section className="stack" aria-labelledby="h-questions">
				<h2 id="h-questions">Daftar soal</h2>
				{questions.length === 0 ? (
					<p className="muted">
						Belum ada soal. Tambah soal atau import dari template.
					</p>
				) : (
					<ol className="question-list">
						{questions.map((q, i) => (
							<li key={q.id} className="card">
								<div className="stack">
									<p className="muted">
										No. {i + 1} · {TYPE_LABEL[q.type]} · bobot {q.weight}
										{q.stimulus_id && " · memakai stimulus"}
										{q.image_url && " · bergambar"}
									</p>
									<p className="clamp">{q.stem}</p>
								</div>
								{can("EDIT") && (
									<div className="row-actions">
										<button
											type="button"
											className="btn btn-secondary"
											onClick={() => {
												setEditing(q);
												setView("edit");
												window.scrollTo({ top: 0 });
											}}
										>
											Edit
										</button>
										<button
											type="button"
											className="btn btn-ghost danger"
											onClick={() => remove(q)}
										>
											Hapus
										</button>
									</div>
								)}
							</li>
						))}
					</ol>
				)}
			</section>

			{can("EDIT") && (
				<section className="card stack" aria-labelledby="h-stimuli">
					<h2 id="h-stimuli">Stimulus bersama</h2>
					<p className="muted">
						Bacaan yang dipakai beberapa soal sekaligus. Pilih stimulus di
						editor soal.
					</p>
					{stimuli.length > 0 && (
						<ul className="list">
							{stimuli.map((s) => (
								<li key={s.id}>
									<p className="clamp">{s.body_text ?? "(gambar)"}</p>
								</li>
							))}
						</ul>
					)}
					<ActionForm
						label="Tambah stimulus"
						run={async (f) => {
							await api(`${base}/stimuli`, {
								json: { body_text: f.get("body_text") },
							});
							reload();
							return "Stimulus ditambahkan.";
						}}
					>
						<label className="field">
							<span>Teks stimulus</span>
							<textarea name="body_text" rows={3} required maxLength={10000} />
						</label>
					</ActionForm>
				</section>
			)}
		</div>
	);
}

function BackLink() {
	return (
		<div>
			<button
				type="button"
				className="btn btn-ghost"
				onClick={() => navigate("/teacher/questions")}
			>
				← Semua bank soal
			</button>
		</div>
	);
}

function ToggleButton({
	active,
	onClick,
	children,
}: {
	active: boolean;
	onClick: () => void;
	children: string;
}) {
	return (
		<button
			type="button"
			className="btn btn-secondary"
			aria-pressed={active}
			onClick={onClick}
		>
			{children}
		</button>
	);
}

function BankPreview({ base }: { base: string }) {
	const [items, setItems] = useState<StudentQuestion[] | null>(null);
	const [error, setError] = useState("");
	useEffect(() => {
		api<StudentQuestion[]>(`${base}/preview`)
			.then(setItems)
			.catch((err) => setError(message(err)));
	}, [base]);
	return (
		<section className="stack" aria-labelledby="h-preview">
			<h2 id="h-preview">Pratinjau seperti siswa</h2>
			<p className="muted">
				Kunci jawaban tidak dikirim ke tampilan ini. Urutan acak diterapkan saat
				ujian.
			</p>
			<Alert kind="error">{error}</Alert>
			<div className="reading stack">
				{items?.map((q, i) => (
					<StudentQuestionView
						key={q.id}
						q={q}
						number={i + 1}
						total={items.length}
					/>
				))}
			</div>
		</section>
	);
}

function CopyPanel({ base, currentId }: { base: string; currentId: string }) {
	const [targets, setTargets] = useState<Bank[]>([]);
	useEffect(() => {
		api<Bank[]>("/question-banks")
			.then((banks) =>
				setTargets(
					banks.filter(
						(b) => b.id !== currentId && LEVEL[b.access] >= LEVEL.EDIT,
					),
				),
			)
			.catch(() => setTargets([]));
	}, [currentId]);
	return (
		<section className="card stack" aria-labelledby="h-copy">
			<h2 id="h-copy">Salin semua soal ke bank lain</h2>
			{targets.length === 0 ? (
				<p className="muted">
					Belum ada bank lain yang bisa Anda edit. Buat bank soal sendiri dulu.
				</p>
			) : (
				<ActionForm
					label="Salin soal"
					run={async (f) => {
						const res = await api<{ copied: number }>(`${base}/copy`, {
							json: { target_bank_id: f.get("target") },
						});
						return `${res.copied} soal disalin.`;
					}}
				>
					<Select
						label="Bank tujuan"
						name="target"
						options={targets.map((b) => ({ value: b.id, label: b.title }))}
					/>
				</ActionForm>
			)}
		</section>
	);
}

type Share = { teacher_id: string; display_name: string; permission: Access };

function SharePanel({ base }: { base: string }) {
	const [shares, setShares] = useState<Share[]>([]);
	const [teachers, setTeachers] = useState<
		{ id: string; display_name: string }[]
	>([]);
	const [error, setError] = useState("");
	const reload = useCallback(() => {
		Promise.all([
			api<Share[]>(`${base}/shares`),
			api<{ id: string; display_name: string }[]>("/teachers"),
		])
			.then(([s, t]) => {
				setShares(s);
				setTeachers(t);
			})
			.catch((err) => setError(message(err)));
	}, [base]);
	useEffect(reload, [reload]);

	async function revoke(s: Share) {
		if (!window.confirm(`Cabut akses ${s.display_name}?`)) return;
		try {
			await api(`${base}/shares/${s.teacher_id}`, { method: "DELETE" });
			reload();
		} catch (err) {
			setError(message(err));
		}
	}

	return (
		<section className="card stack" aria-labelledby="h-share">
			<h2 id="h-share">Bagikan ke guru lain</h2>
			<Alert kind="error">{error}</Alert>
			{shares.length === 0 ? (
				<p className="muted">Bank ini belum dibagikan.</p>
			) : (
				<ul className="list">
					{shares.map((s) => (
						<li key={s.teacher_id}>
							<span>
								{s.display_name} — {ACCESS_LABEL[s.permission]}
							</span>
							<button
								type="button"
								className="btn btn-ghost danger"
								onClick={() => revoke(s)}
							>
								Cabut
							</button>
						</li>
					))}
				</ul>
			)}
			<ActionForm
				label="Simpan akses"
				run={async (f) => {
					await api(`${base}/shares`, {
						json: {
							teacher_id: f.get("teacher_id"),
							permission: f.get("permission"),
						},
					});
					reload();
					return "Akses disimpan.";
				}}
			>
				<Select
					label="Guru"
					name="teacher_id"
					options={teachers.map((t) => ({
						value: t.id,
						label: t.display_name,
					}))}
				/>
				<Select
					label="Akses"
					name="permission"
					options={[
						{ value: "VIEW", label: "Lihat (termasuk kunci)" },
						{ value: "COPY", label: "Lihat & salin" },
						{ value: "EDIT", label: "Edit soal" },
					]}
				/>
			</ActionForm>
		</section>
	);
}
