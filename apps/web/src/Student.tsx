import {
	type FormEvent,
	useCallback,
	useEffect,
	useRef,
	useState,
} from "react";
import { ApiError, api } from "./api";
import { queueAll, queueClear, queueDelete, queuePut } from "./offlineQueue";
import {
	type Answer,
	LETTER,
	type StudentQuestion,
	StudentQuestionView,
} from "./QuestionEditor";
import { Alert, message, navigate } from "./ui";

const LATE_FLAG = "localcbt.lateAnswers";
const HEARTBEAT_MS = 5000;

type ExamItem = {
	id: string;
	title: string;
	subject_name: string;
	duration_seconds: number;
	start_window_from: string;
	start_window_until: string;
	status: "SCHEDULED" | "AVAILABLE" | "IN_PROGRESS" | "COMPLETED" | "CLOSED";
	attempt_id: string | null;
};
type Timer = {
	state: string;
	remaining_seconds: number;
	server_now: string;
	pause_allowance_seconds: number;
	heartbeat_timeout_seconds: number;
	announcements_count: number;
};
type SavedAnswer = {
	question_id: string;
	answer: Answer | null;
	marked_for_review: boolean;
	client_revision: number;
	saved_at: string;
};
type Attempt = {
	id: string;
	exam_id: string;
	exam_title: string;
	state: "IN_PROGRESS" | "PAUSED" | "SUBMITTED" | "GRADED";
	timer: Timer;
	questions: StudentQuestion[];
	answers: SavedAnswer[];
	submitted_at: string | null;
	receipt_id: string | null;
};

const fmtDate = (iso: string) =>
	new Date(iso).toLocaleString("id-ID", {
		dateStyle: "medium",
		timeStyle: "short",
	});
const fmtTime = (iso: string) =>
	new Date(iso).toLocaleTimeString("id-ID", {
		hour: "2-digit",
		minute: "2-digit",
	});
const idem = () => ({ "Idempotency-Key": crypto.randomUUID() });

export function StudentPage({ path }: { path: string }) {
	const [, , kind, id, sub] = path.split("/");
	if (kind === "exams" && id) return <TokenStart examId={id} />;
	if (kind === "attempts" && id && sub === "done")
		return <Done attemptId={id} />;
	if (kind === "attempts" && id) return <Workspace key={id} attemptId={id} />;
	return <ExamList />;
}

// ---- S-01 Daftar ujian --------------------------------------------------------

function ExamList() {
	const [exams, setExams] = useState<ExamItem[] | null>(null);
	const [error, setError] = useState("");
	useEffect(() => {
		api<ExamItem[]>("/student/exams")
			.then(setExams)
			.catch((err) => setError(message(err)));
	}, []);

	const action = (e: ExamItem) => {
		switch (e.status) {
			case "AVAILABLE":
				return (
					<button
						type="button"
						className="btn btn-primary"
						onClick={() => navigate(`/student/exams/${e.id}`)}
					>
						Mulai
					</button>
				);
			case "IN_PROGRESS":
				return (
					<button
						type="button"
						className="btn btn-primary"
						onClick={() => navigate(`/student/attempts/${e.attempt_id}`)}
					>
						Lanjutkan
					</button>
				);
			case "COMPLETED":
				return (
					<button
						type="button"
						className="btn btn-secondary"
						onClick={() => navigate(`/student/attempts/${e.attempt_id}/done`)}
					>
						Lihat bukti
					</button>
				);
			case "SCHEDULED":
				return (
					<span className="muted">Dibuka {fmtDate(e.start_window_from)}</span>
				);
			default:
				return <span className="muted">Periode mulai sudah berakhir</span>;
		}
	};

	return (
		<div className="stack reading">
			<Alert kind="error">{error}</Alert>
			{exams?.length === 0 && (
				<p className="muted">Belum ada ujian untuk Anda saat ini.</p>
			)}
			<ul className="question-list">
				{exams?.map((e) => (
					<li key={e.id} className="card">
						<div className="stack">
							<strong>{e.title}</strong>
							<p className="muted">
								{e.subject_name} · {e.duration_seconds / 60} menit
							</p>
							<p className="muted">
								Mulai {fmtDate(e.start_window_from)} –{" "}
								{fmtDate(e.start_window_until)}
							</p>
						</div>
						<div className="row-actions">{action(e)}</div>
					</li>
				))}
			</ul>
		</div>
	);
}

// ---- S-02/S-03 Token & instruksi ----------------------------------------------

function TokenStart({ examId }: { examId: string }) {
	const [exam, setExam] = useState<ExamItem | null>(null);
	const [grant, setGrant] = useState("");
	const [agreed, setAgreed] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		api<ExamItem[]>("/student/exams")
			.then((list) => {
				const found = list.find((e) => e.id === examId);
				if (found?.attempt_id)
					navigate(`/student/attempts/${found.attempt_id}`);
				else setExam(found ?? null);
			})
			.catch((err) => setError(message(err)));
	}, [examId]);

	async function verify(e: FormEvent<HTMLFormElement>) {
		e.preventDefault();
		setBusy(true);
		setError("");
		try {
			const res = await api<{ start_grant: string }>(
				`/student/exams/${examId}/token/verify`,
				{ json: { token: new FormData(e.currentTarget).get("token") } },
			);
			setGrant(res.start_grant);
		} catch (err) {
			setError(message(err));
		} finally {
			setBusy(false);
		}
	}

	async function begin() {
		setBusy(true);
		setError("");
		try {
			const attempt = await api<Attempt>(`/student/exams/${examId}/attempts`, {
				json: { start_grant: grant, confirm_start: true },
				headers: idem(),
			});
			navigate(`/student/attempts/${attempt.id}`);
		} catch (err) {
			if (err instanceof ApiError && err.code === "START_GRANT_INVALID")
				setGrant("");
			setError(message(err));
			setBusy(false);
		}
	}

	return (
		<div className="stack reading">
			<div>
				<button
					type="button"
					className="btn btn-ghost"
					onClick={() => navigate("/student")}
				>
					← Daftar ujian
				</button>
			</div>
			{exam && <h2 className="h1">{exam.title}</h2>}
			<Alert kind="error">{error}</Alert>
			{!grant ? (
				<form onSubmit={verify} className="card stack">
					<label className="field">
						<span>Token ujian dari pengawas</span>
						<input
							name="token"
							type="password"
							autoComplete="off"
							autoCapitalize="characters"
							minLength={4}
							maxLength={32}
							required
						/>
					</label>
					<div>
						<button type="submit" className="btn btn-primary" disabled={busy}>
							{busy ? "Memeriksa…" : "Lanjut"}
						</button>
					</div>
				</form>
			) : (
				<section className="card stack" aria-labelledby="h-rules">
					<h2 id="h-rules">Sebelum mulai</h2>
					<ul className="rules">
						{exam && (
							<li>
								Waktu mengerjakan {exam.duration_seconds / 60} menit, dihitung
								sejak Anda menekan Mulai. Waktu mengikuti server, bukan jam
								perangkat.
							</li>
						)}
						<li>
							Jawaban tersimpan otomatis. Perhatikan tanda “Tersimpan di
							server”.
						</li>
						<li>
							Anda bebas berpindah nomor soal dan menandai soal untuk ditinjau.
						</li>
						<li>
							Bila waktu habis, jawaban yang sudah tersimpan dikumpulkan
							otomatis.
						</li>
						<li>
							Bila ada kendala perangkat atau jaringan, segera hubungi pengawas.
						</li>
					</ul>
					<label className="check">
						<input
							type="checkbox"
							checked={agreed}
							onChange={(e) => setAgreed(e.target.checked)}
						/>
						Saya sudah membaca petunjuk dan siap mengerjakan
					</label>
					<div>
						<button
							type="button"
							className="btn btn-primary"
							disabled={!agreed || busy}
							onClick={begin}
						>
							{busy ? "Menyiapkan…" : "Mulai ujian"}
						</button>
					</div>
				</section>
			)}
		</div>
	);
}

// ---- S-04/S-05 Workspace ------------------------------------------------------

type Local = {
	answer: Answer | null;
	marked: boolean;
	rev: number;
	// queued = tersimpan di perangkat, belum tersinkron (jaringan putus)
	status: "saved" | "saving" | "queued" | "failed";
	savedAt?: string;
	error?: string;
};

function isAnswered(a: Answer | null | undefined) {
	if (!a) return false;
	if (a.type === "MULTIPLE_CHOICE") return a.selected_option_ids.length > 0;
	if (a.type === "CATEGORY_CHOICE") return a.choices.length > 0;
	return true;
}

type Clock = {
	announcements: number;
	left: number;
	offline: boolean;
	frozen: boolean;
	capReached: boolean;
};

function useServerTimer(
	attemptId: string,
	initial: Timer | undefined,
	onEnd: () => void,
): Clock {
	// Hitung mundur lokal hanya untuk tampilan; patokannya sisa waktu dari server. Saat offline,
	// klien meniru jeda server: setelah heartbeat_timeout, waktu dibekukan selama jatah jeda.
	const base = useRef({ remaining: 0, at: 0, allowance: 0, timeout: 15 });
	const failures = useRef(0);
	const ending = useRef(false);
	const announcements = useRef(0);
	const [clock, setClock] = useState<Clock>({
		announcements: 0,
		left: 0,
		offline: false,
		frozen: false,
		capReached: false,
	});

	const compute = useCallback((): Clock => {
		const b = base.current;
		const elapsed = (performance.now() - b.at) / 1000;
		const offline = failures.current >= 2;
		const frozenFor = offline
			? Math.min(Math.max(0, elapsed - b.timeout), b.allowance)
			: 0;
		return {
			announcements: announcements.current,
			left: Math.max(0, Math.ceil(b.remaining - (elapsed - frozenFor))),
			offline,
			frozen: offline && elapsed > b.timeout && frozenFor < b.allowance,
			capReached: offline && elapsed > b.timeout && frozenFor >= b.allowance,
		};
	}, []);

	const sync = useCallback(
		(t: Timer) => {
			failures.current = 0;
			announcements.current = t.announcements_count;
			base.current = {
				remaining: t.remaining_seconds,
				at: performance.now(),
				allowance: t.pause_allowance_seconds,
				timeout: t.heartbeat_timeout_seconds,
			};
			setClock(compute());
		},
		[compute],
	);

	useEffect(() => {
		if (initial) sync(initial);
	}, [initial, sync]);

	const heartbeat = useCallback(async () => {
		try {
			const t = await api<Timer>(`/student/attempts/${attemptId}/heartbeat`, {
				json: { tab_visible: document.visibilityState === "visible" },
				timeoutMs: 4000,
			});
			if (t.state !== "IN_PROGRESS" && t.state !== "PAUSED") onEnd();
			else sync(t);
		} catch {
			failures.current += 1;
			setClock(compute());
		}
	}, [attemptId, onEnd, sync, compute]);

	useEffect(() => {
		const tick = setInterval(() => {
			const next = compute();
			setClock(next);
			if (next.left === 0 && !next.offline && !ending.current) {
				ending.current = true;
				heartbeat().finally(() => {
					ending.current = false;
				});
			}
		}, 1000);
		const beat = setInterval(heartbeat, HEARTBEAT_MS);
		// Pindah tab dikirim saat itu juga (indikator untuk pengawas, bukan vonis).
		document.addEventListener("visibilitychange", heartbeat);
		return () => {
			clearInterval(tick);
			clearInterval(beat);
			document.removeEventListener("visibilitychange", heartbeat);
		};
	}, [heartbeat, compute]);

	return clock;
}

function TimerBadge({ seconds, frozen }: { seconds: number; frozen: boolean }) {
	const h = Math.floor(seconds / 3600);
	const m = Math.floor((seconds % 3600) / 60);
	const s = seconds % 60;
	const text = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
	const level = frozen
		? "paused"
		: seconds <= 60
			? "critical"
			: seconds <= 600
				? "low"
				: "normal";
	const announce =
		seconds === 600
			? "Sisa waktu 10 menit."
			: seconds === 60
				? "Sisa waktu 1 menit."
				: seconds === 0
					? "Waktu habis."
					: "";
	return (
		<span className={`timer timer-${level}`}>
			<span className="sr-only">Sisa waktu </span>
			{frozen && <span aria-hidden="true">⏸ </span>}
			{text}
			{frozen && <span className="sr-only"> (waktu dijeda)</span>}
			<span className="sr-only" aria-live="assertive">
				{announce}
			</span>
		</span>
	);
}

function Workspace({ attemptId }: { attemptId: string }) {
	const [attempt, setAttempt] = useState<Attempt | null>(null);
	const [local, setLocal] = useState<Record<string, Local>>({});
	const [index, setIndex] = useState(0);
	const [error, setError] = useState("");
	const latest = useRef<Record<string, Local>>({});
	const inflight = useRef(new Set<string>());
	const navDialog = useRef<HTMLDialogElement>(null);
	const submitDialog = useRef<HTMLDialogElement>(null);
	const finished = useCallback(
		() => navigate(`/student/attempts/${attemptId}/done`),
		[attemptId],
	);

	// load() dan send() saling memanggil; send hanya membaca ref, jadi aman lewat ref ini.
	const sendRef = useRef<(qid: string) => void>(() => {});

	const load = useCallback(async () => {
		try {
			const a = await api<Attempt>(`/student/attempts/${attemptId}`);
			if (a.state === "SUBMITTED" || a.state === "GRADED") return finished();
			const fromServer: Record<string, Local> = {};
			for (const s of a.answers) {
				fromServer[s.question_id] = {
					answer: s.answer,
					marked: s.marked_for_review,
					rev: s.client_revision,
					status: "saved",
					savedAt: s.saved_at,
				};
			}
			// Jawaban yang masih antre di perangkat (mis. reload saat offline) dan lebih baru dari
			// yang diterima server dikirim ulang; sisanya dibuang. Antrian attempt lain dihapus.
			await queueClear(attemptId);
			const pending: string[] = [];
			for (const e of await queueAll()) {
				if (e.rev > (fromServer[e.questionId]?.rev ?? 0)) {
					fromServer[e.questionId] = {
						answer: e.answer,
						marked: e.marked,
						rev: e.rev,
						status: "queued",
					};
					pending.push(e.questionId);
				} else {
					await queueDelete(e.key);
				}
			}
			latest.current = fromServer;
			setLocal(fromServer);
			setAttempt(a);
			for (const qid of pending) sendRef.current(qid);
		} catch (err) {
			setError(message(err));
		}
	}, [attemptId, finished]);

	useEffect(() => {
		load();
	}, [load]);

	const clock = useServerTimer(attemptId, attempt?.timer, finished);
	const [notices, setNotices] = useState<
		{ message: string; issued_at: string }[]
	>([]);
	// Pengumuman diambil saat dibuka dan setiap jumlahnya bertambah (juga setelah reconnect).
	useEffect(() => {
		if (clock.announcements >= 0) {
			api<{ message: string; issued_at: string }[]>(
				`/student/attempts/${attemptId}/announcements`,
			)
				.then(setNotices)
				.catch(() => {});
		}
	}, [attemptId, clock.announcements]);

	// Waktu habis sebelum antrian terkirim: server menolak (ADR-006), siswa diberi instruksi.
	const lockedOut = useCallback(async () => {
		const late = Object.values(latest.current).filter(
			(l) =>
				l.status === "queued" || l.status === "failed" || l.status === "saving",
		).length;
		await queueClear();
		try {
			if (late) sessionStorage.setItem(LATE_FLAG, String(late));
		} catch {}
		finished();
	}, [finished]);

	useEffect(() => {
		const resend = () => {
			for (const [qid, l] of Object.entries(latest.current)) {
				if (l.status === "queued" || l.status === "failed") send(qid);
			}
		};
		window.addEventListener("online", resend);
		return () => window.removeEventListener("online", resend);
	});

	const put = (qid: string, value: Local) => {
		latest.current = { ...latest.current, [qid]: value };
		setLocal(latest.current);
	};

	// Satu permintaan per soal; perubahan terbaru selalu menang. Kunci idempotensi dipakai ulang
	// saat mencoba lagi, sehingga ACK yang hilang tidak membuat simpanan ganda.
	async function send(qid: string) {
		if (inflight.current.has(qid)) return;
		inflight.current.add(qid);
		let delay = 1000;
		try {
			for (;;) {
				const draft = latest.current[qid];
				const key = crypto.randomUUID();
				let receipt: { saved_at: string } | null = null;
				while (!receipt) {
					try {
						receipt = await api(
							`/student/attempts/${attemptId}/answers/${qid}`,
							{
								method: "PUT",
								json: {
									answer: isAnswered(draft.answer) ? draft.answer : null,
									client_revision: draft.rev,
									marked_for_review: draft.marked,
								},
								headers: { "Idempotency-Key": key },
							},
						);
					} catch (err) {
						if (err instanceof ApiError && err.code === "ATTEMPT_LOCKED")
							return lockedOut();
						if (err instanceof ApiError && err.code === "REVISION_CONFLICT") {
							await load();
							return;
						}
						const retryable =
							!(err instanceof ApiError) ||
							err.status === 0 ||
							err.status >= 500;
						put(qid, {
							...latest.current[qid],
							status: retryable ? "queued" : "failed",
							error: retryable ? undefined : message(err),
						});
						if (!retryable) return;
						await new Promise((r) => setTimeout(r, delay));
						delay = Math.min(delay * 2, 5000);
					}
				}
				const now = latest.current[qid];
				if (now.rev === draft.rev) {
					put(qid, {
						...now,
						status: "saved",
						savedAt: receipt.saved_at,
						error: undefined,
					});
					await queueDelete(`${attemptId}:${qid}`);
					return;
				}
				// Ada perubahan baru selama menunggu: kirim lagi versi terbaru.
			}
		} finally {
			inflight.current.delete(qid);
		}
	}

	sendRef.current = send;

	function change(
		qid: string,
		patch: Partial<Pick<Local, "answer" | "marked">>,
	) {
		const cur = latest.current[qid] ?? {
			answer: null,
			marked: false,
			rev: 0,
			status: "saved",
		};
		const next: Local = {
			...cur,
			...patch,
			rev: cur.rev + 1,
			status: "saving",
		};
		put(qid, next);
		// Ditulis ke perangkat SEBELUM dikirim: reload/tab crash di tengah jalan tidak menghilangkannya.
		queuePut({
			key: `${attemptId}:${qid}`,
			attemptId,
			questionId: qid,
			answer: next.answer,
			marked: next.marked,
			rev: next.rev,
		}).finally(() => send(qid));
	}

	if (!attempt) {
		return (
			<div className="center stack">
				<Alert kind="error">{error}</Alert>
				{!error && <p className="muted">Menyiapkan soal…</p>}
			</div>
		);
	}

	const qs = attempt.questions;
	const q = qs[index];
	const states = Object.values(local);
	const saving = states.some((s) => s.status === "saving");
	const failed = states.find((s) => s.status === "failed");
	const queued = states.filter((s) => s.status === "queued").length;
	const lastSaved = states
		.map((s) => s.savedAt)
		.filter(Boolean)
		.sort()
		.at(-1);
	const answered = qs.filter((x) => isAnswered(local[x.id]?.answer)).length;
	const marked = qs.filter((x) => local[x.id]?.marked).length;
	const go = (i: number) => {
		setIndex(i);
		navDialog.current?.close();
		document.querySelector(".exam-main")?.scrollTo({ top: 0 });
	};

	const navigator = (
		<nav className="navigator" aria-label="Nomor soal">
			<p className="muted">
				Terjawab {answered} / {qs.length}
				{marked > 0 && ` · ditandai ${marked}`}
			</p>
			<ol>
				{qs.map((x, i) => {
					const st = local[x.id];
					const done = isAnswered(st?.answer);
					const label = [
						`Nomor ${i + 1}`,
						done ? "sudah dijawab" : "belum dijawab",
						st?.marked ? "ditandai" : "",
					]
						.filter(Boolean)
						.join(", ");
					return (
						<li key={x.id}>
							<button
								type="button"
								className={`nav-num${done ? " answered" : ""}${st?.marked ? " marked" : ""}`}
								aria-current={i === index ? "step" : undefined}
								aria-label={label}
								onClick={() => go(i)}
							>
								{i + 1}
								{st?.marked && <span aria-hidden="true">⚑</span>}
							</button>
						</li>
					);
				})}
			</ol>
			<p className="legend muted">
				<span className="nav-num answered sample" aria-hidden="true" /> dijawab
				· <span aria-hidden="true">⚑</span> ditandai
			</p>
		</nav>
	);

	const saveText = queued
		? `${queued} jawaban tersimpan di perangkat, belum tersinkron`
		: saving
			? "Menyimpan…"
			: failed
				? "Gagal menyimpan — mencoba lagi. Jangan tutup halaman."
				: lastSaved
					? `Tersimpan di server pukul ${fmtTime(lastSaved)}`
					: "Belum ada jawaban";

	return (
		<div className="exam">
			<header className="exam-header">
				<strong className="exam-title">{attempt.exam_title}</strong>
				<TimerBadge seconds={clock.left} frozen={clock.frozen} />
				<span
					className={`save save-${queued ? "queued" : saving ? "saving" : failed ? "failed" : lastSaved ? "saved" : "empty"}`}
					role="status"
					aria-live="polite"
				>
					{(queued || saving || failed || lastSaved) && (
						<span aria-hidden="true">
							{queued ? "⇡" : saving ? "…" : failed ? "!" : "✓"}{" "}
						</span>
					)}
					{saveText}
				</span>
			</header>
			<div className="exam-body">
				<main className="exam-main" tabIndex={-1}>
					<Alert kind="error">{error}</Alert>
					{notices.length > 0 && (
						<section
							className="notices"
							aria-label="Pengumuman pengawas"
							aria-live="polite"
						>
							{notices.map((n) => (
								<p key={n.issued_at} className="alert alert-info">
									<strong>Pengumuman {fmtTime(n.issued_at)}:</strong>{" "}
									{n.message}
								</p>
							))}
						</section>
					)}
					{clock.offline && (
						<Alert kind="warning">
							Koneksi ke server terputus. Jawaban baru tersimpan di perangkat
							dan belum dikirim.{" "}
							{clock.frozen
								? "Waktu ujian dijeda sementara."
								: clock.capReached
									? "Batas jeda telah tercapai. Waktu ujian kembali berjalan. Hubungi pengawas."
									: "Hubungi pengawas bila tidak segera tersambung."}
						</Alert>
					)}
					{q && (
						<StudentQuestionView
							key={q.id}
							q={q}
							number={index + 1}
							total={qs.length}
							value={local[q.id]?.answer ?? null}
							onChange={(answer) => change(q.id, { answer })}
						/>
					)}
					{q && local[q.id]?.status === "failed" && local[q.id]?.error && (
						<Alert kind="warning">{local[q.id]?.error}</Alert>
					)}
					<div className="exam-actions">
						<button
							type="button"
							className="btn btn-secondary"
							aria-pressed={Boolean(local[q?.id]?.marked)}
							onClick={() => change(q.id, { marked: !local[q.id]?.marked })}
						>
							⚑ {local[q?.id]?.marked ? "Ditandai" : "Tandai untuk ditinjau"}
						</button>
					</div>
					<div className="exam-actions">
						<button
							type="button"
							className="btn btn-secondary"
							disabled={index === 0}
							onClick={() => go(index - 1)}
						>
							← Sebelumnya
						</button>
						<button
							type="button"
							className="btn btn-secondary"
							disabled={index === qs.length - 1}
							onClick={() => go(index + 1)}
						>
							Berikutnya →
						</button>
					</div>
				</main>
				<aside className="exam-side">
					{navigator}
					<button
						type="button"
						className="btn btn-primary"
						onClick={() => submitDialog.current?.showModal()}
					>
						Kumpulkan ujian
					</button>
				</aside>
			</div>
			<div className="exam-bottom">
				<button
					type="button"
					className="btn btn-secondary"
					onClick={() => navDialog.current?.showModal()}
				>
					Nomor soal
				</button>
				<button
					type="button"
					className="btn btn-primary"
					onClick={() => submitDialog.current?.showModal()}
				>
					Kumpulkan
				</button>
			</div>
			<dialog ref={navDialog} className="dialog sheet" aria-label="Nomor soal">
				{navigator}
				<button
					type="button"
					className="btn btn-ghost"
					onClick={() => navDialog.current?.close()}
				>
					Tutup
				</button>
			</dialog>
			<SubmitDialog
				ref={submitDialog}
				attemptId={attemptId}
				total={qs.length}
				answered={answered}
				marked={marked}
				blocked={saving || queued > 0 || Boolean(failed)}
				onSubmitted={() => queueClear().finally(finished)}
			/>
		</div>
	);
}

function SubmitDialog({
	ref,
	attemptId,
	total,
	answered,
	marked,
	blocked,
	onSubmitted,
}: {
	ref: React.Ref<HTMLDialogElement>;
	attemptId: string;
	total: number;
	answered: number;
	marked: number;
	blocked: boolean;
	onSubmitted: () => void;
}) {
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const key = useRef(crypto.randomUUID());

	async function submit() {
		setBusy(true);
		setError("");
		try {
			await api(`/student/attempts/${attemptId}/submit`, {
				json: { confirm: true },
				headers: { "Idempotency-Key": key.current },
			});
			onSubmitted();
		} catch (err) {
			setError(message(err));
			setBusy(false);
		}
	}

	return (
		<dialog ref={ref} className="dialog" aria-labelledby="h-submit">
			<div className="stack">
				<h2 id="h-submit" tabIndex={-1}>
					Kumpulkan ujian?
				</h2>
				<ul className="rules">
					<li>Sudah dijawab: {answered}</li>
					<li className={total - answered > 0 ? "warn" : undefined}>
						Belum dijawab: {total - answered}
					</li>
					<li>Ditandai untuk ditinjau: {marked}</li>
				</ul>
				<p>Setelah dikumpulkan, jawaban tidak dapat diubah lagi.</p>
				{blocked && (
					<Alert kind="warning">
						Masih ada jawaban yang belum tersimpan di server.
					</Alert>
				)}
				<Alert kind="error">{error}</Alert>
				<div className="form-row">
					<button
						type="button"
						className="btn btn-primary"
						disabled={blocked || busy}
						onClick={submit}
					>
						{busy ? "Mengumpulkan…" : "Ya, kumpulkan"}
					</button>
					<button
						type="button"
						className="btn btn-secondary"
						onClick={(e) => e.currentTarget.closest("dialog")?.close()}
					>
						Kembali
					</button>
				</div>
			</div>
		</dialog>
	);
}

// ---- S-06/S-07 Bukti, nilai, pembahasan ---------------------------------------

type ReviewItem = {
	question: StudentQuestion;
	own_answer: Answer | null;
	marked: boolean;
	earned?: number | null;
	correct_answer?: {
		correct_option_ids?: string[];
		statements?: Record<string, boolean>;
	};
};

function keyText(item: ReviewItem) {
	const key = item.correct_answer;
	if (!key) return null;
	if (key.statements) {
		return item.question.statements
			.map((s) => `${s.text}: ${key.statements?.[s.id] ? "Benar" : "Salah"}`)
			.join(" · ");
	}
	return item.question.options
		.map((o, i) => (key.correct_option_ids?.includes(o.id) ? LETTER[i] : null))
		.filter(Boolean)
		.join(", ");
}

function Done({ attemptId }: { attemptId: string }) {
	const [attempt, setAttempt] = useState<Attempt | null>(null);
	const [result, setResult] = useState<
		{ total_score: number; max_score: number } | string
	>("");
	const [review, setReview] = useState<ReviewItem[] | string | null>(null);
	const [late] = useState(() => {
		try {
			const n = sessionStorage.getItem(LATE_FLAG);
			sessionStorage.removeItem(LATE_FLAG);
			return Number(n) || 0;
		} catch {
			return 0;
		}
	});
	const [error, setError] = useState("");

	useEffect(() => {
		api<Attempt>(`/student/attempts/${attemptId}`)
			.then((a) => {
				if (a.state === "IN_PROGRESS")
					navigate(`/student/attempts/${attemptId}`);
				setAttempt(a);
			})
			.catch((err) => setError(message(err)));
		api<{ total_score: number; max_score: number }>(
			`/student/attempts/${attemptId}/result`,
		)
			.then(setResult)
			.catch((err) => setResult(message(err)));
	}, [attemptId]);

	// Judul baru ada setelah attempt termuat; fokus ke sana agar pembaca layar mengumumkannya.
	const loaded = attempt !== null;
	useEffect(() => {
		if (loaded) document.querySelector<HTMLElement>("#h-done")?.focus();
	}, [loaded]);

	async function openReview() {
		try {
			const r = await api<{ questions: ReviewItem[] }>(
				`/student/attempts/${attemptId}/review`,
			);
			setReview(r.questions);
		} catch (err) {
			setReview(message(err));
		}
	}

	return (
		<div className="stack-lg reading">
			<Alert kind="error">{error}</Alert>
			{late > 0 && (
				<Alert kind="warning">
					{late} jawaban belum terkirim ke server sebelum waktu habis sehingga
					tidak dinilai. Segera hubungi pengawas.
				</Alert>
			)}
			{attempt && (
				<section className="card stack" aria-labelledby="h-done">
					<h2 id="h-done" tabIndex={-1}>
						Ujian berhasil dikumpulkan.
					</h2>
					<p>{attempt.exam_title}</p>
					<p className="muted">
						Waktu server:{" "}
						{attempt.submitted_at && fmtDate(attempt.submitted_at)} · Bukti{" "}
						<strong>{attempt.receipt_id}</strong>
					</p>
					{typeof result === "string" ? (
						result && <p className="muted">{result}</p>
					) : (
						<p className="score">
							Nilai: <strong>{result.total_score}</strong> dari{" "}
							{result.max_score}
						</p>
					)}
					<div className="form-row">
						<button
							type="button"
							className="btn btn-secondary"
							onClick={openReview}
						>
							Lihat pembahasan
						</button>
						<button
							type="button"
							className="btn btn-ghost"
							onClick={() => navigate("/student")}
						>
							Kembali ke daftar ujian
						</button>
					</div>
					{typeof review === "string" && <p className="muted">{review}</p>}
				</section>
			)}
			{Array.isArray(review) &&
				review.map((item, i) => (
					<div key={item.question.id} className="stack">
						<StudentQuestionView
							q={item.question}
							number={i + 1}
							total={review.length}
							value={item.own_answer}
							disabled
						/>
						<p className="muted">
							{item.own_answer
								? "Jawaban Anda ditandai di atas."
								: "Tidak dijawab."}
							{item.earned != null && ` Nilai soal: ${item.earned}.`}
							{keyText(item) && ` Kunci: ${keyText(item)}.`}
						</p>
					</div>
				))}
		</div>
	);
}
