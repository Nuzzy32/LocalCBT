import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Alert, message, navigate } from "./ui";

type Status =
	| "NOT_STARTED"
	| "ACTIVE"
	| "DISCONNECTED"
	| "PAUSED"
	| "SUBMITTED";
type Participant = {
	student_id: string;
	nis: string;
	display_name: string;
	attempt_id: string | null;
	status: Status;
	pause_consumed_sec: number;
	remaining_seconds: number | null;
	answered_count: number;
	tab_hidden: number;
	permit_pending: boolean;
};
type Snapshot = {
	exam_id: string;
	server_now: string;
	total_count: number;
	counts: Record<string, number>;
	participants: Participant[];
	announcements: { message: string; issued_at: string; sender: string }[];
};
type SupervisedExam = {
	id: string;
	title: string;
	subject_name: string;
	start_window_from: string;
	duration_sec: number;
	status: "PUBLISHED" | "ACTIVE" | "CLOSED";
	is_author: boolean;
};
type EventRow = {
	kind: string;
	at: string;
	detail: string | null;
	seconds: number | null;
	reason: string | null;
};

const STATUS_LABEL: Record<Status, string> = {
	NOT_STARTED: "Belum mulai",
	ACTIVE: "Aktif",
	DISCONNECTED: "Terputus",
	PAUSED: "Dijeda",
	SUBMITTED: "Selesai",
};
const STATUS_ICON: Record<Status, string> = {
	NOT_STARTED: "○",
	ACTIVE: "●",
	DISCONNECTED: "⚠",
	PAUSED: "⏸",
	SUBMITTED: "✓",
};
const EVENT_LABEL: Record<string, string> = {
	PAUSE: "Jeda koneksi",
	TAB_HIDDEN: "Pindah tab / aplikasi",
	TIME_EXTENDED: "Tambah waktu",
	DEVICE_SWITCH_APPROVED: "Izin pindah perangkat",
	SESSION_RESET: "Reset sesi",
};
const fmtTime = (iso: string) =>
	new Date(iso).toLocaleTimeString("id-ID", {
		hour: "2-digit",
		minute: "2-digit",
	});
const mmss = (s: number | null) =>
	s == null ? "–" : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export function ProctorPage({ path }: { path: string }) {
	const [, , kind, id] = path.split("/");
	if (kind === "exams" && id) return <Monitor key={id} examId={id} />;
	return <SupervisedList />;
}

function SupervisedList() {
	const [exams, setExams] = useState<SupervisedExam[] | null>(null);
	const [error, setError] = useState("");
	useEffect(() => {
		api<SupervisedExam[]>("/proctor/exams")
			.then(setExams)
			.catch((err) => setError(message(err)));
	}, []);
	return (
		<div className="stack">
			<Alert kind="error">{error}</Alert>
			{exams?.length === 0 && (
				<p className="muted">Belum ada ujian yang Anda awasi.</p>
			)}
			<ul className="question-list">
				{exams?.map((e) => (
					<li key={e.id} className="card">
						<div className="stack">
							<strong>{e.title}</strong>
							<p className="muted">
								{e.subject_name} · mulai{" "}
								{new Date(e.start_window_from).toLocaleString("id-ID", {
									dateStyle: "medium",
									timeStyle: "short",
								})}{" "}
								·{" "}
								{e.status === "ACTIVE"
									? "berlangsung"
									: e.status === "CLOSED"
										? "selesai"
										: "terjadwal"}
							</p>
						</div>
						<button
							type="button"
							className="btn btn-primary"
							onClick={() => navigate(`/proctor/exams/${e.id}`)}
						>
							Pantau
						</button>
					</li>
				))}
			</ul>
		</div>
	);
}

/** Aliran snapshot lewat WebSocket; reconnect dengan backoff. Tiap frame = snapshot penuh. */
function useMonitor(examId: string) {
	const [snap, setSnap] = useState<Snapshot | null>(null);
	const [lastAt, setLastAt] = useState(0);
	const [revoked, setRevoked] = useState(false);
	const [now, setNow] = useState(Date.now());

	const resync = useCallback(() => {
		api<Snapshot>(`/proctor/exams/${examId}/monitor`)
			.then((s) => {
				setSnap(s);
				setLastAt(Date.now());
			})
			.catch(() => {});
	}, [examId]);

	useEffect(() => {
		let ws: WebSocket | null = null;
		let delay = 1000;
		let stopped = false;
		let timer: ReturnType<typeof setTimeout>;
		const connect = () => {
			const proto = window.location.protocol === "https:" ? "wss" : "ws";
			ws = new WebSocket(
				`${proto}://${window.location.host}/api/v1/ws/exams/${examId}`,
			);
			ws.onmessage = (e) => {
				delay = 1000;
				setSnap(JSON.parse(e.data));
				setLastAt(Date.now());
			};
			ws.onclose = (e) => {
				if (stopped) return;
				if (e.code === 1008 && e.wasClean) {
					setRevoked(true);
					return;
				}
				timer = setTimeout(connect, delay);
				delay = Math.min(delay * 2, 10000);
			};
		};
		resync();
		connect();
		const tick = setInterval(() => setNow(Date.now()), 2000);
		return () => {
			stopped = true;
			clearTimeout(timer);
			clearInterval(tick);
			ws?.close();
		};
	}, [examId, resync]);

	return { snap, stale: now - lastAt > 10000, revoked, resync };
}

function Monitor({ examId }: { examId: string }) {
	const { snap, stale, revoked, resync } = useMonitor(examId);
	const [filter, setFilter] = useState<Status | "ALL" | "REVIEW">("ALL");
	const [query, setQuery] = useState("");
	const [selected, setSelected] = useState<Participant | null>(null);
	const drawer = useRef<HTMLDialogElement>(null);

	if (revoked) {
		return (
			<Alert kind="error">
				Akses pengawasan ujian ini dicabut atau sesi berakhir.
			</Alert>
		);
	}
	if (!snap) return <p className="muted">Menghubungkan ke monitor…</p>;

	const rows = snap.participants.filter(
		(p) =>
			(filter === "ALL" ||
				(filter === "REVIEW" ? p.tab_hidden > 0 : p.status === filter)) &&
			(p.display_name + p.nis).toLowerCase().includes(query.toLowerCase()),
	);
	const open = (p: Participant) => {
		setSelected(p);
		drawer.current?.showModal();
	};

	return (
		<div className="stack-lg">
			<div className="stack">
				<div>
					<button
						type="button"
						className="btn btn-ghost"
						onClick={() => navigate("/proctor")}
					>
						← Ujian yang diawasi
					</button>
				</div>
				<fieldset className="counts">
					<legend className="sr-only">
						Ringkasan peserta (klik untuk menyaring)
					</legend>
					{(
						[
							"ACTIVE",
							"DISCONNECTED",
							"PAUSED",
							"SUBMITTED",
							"NOT_STARTED",
						] as Status[]
					).map((s) => (
						<button
							key={s}
							type="button"
							className={`count count-${s.toLowerCase()}`}
							aria-pressed={filter === s}
							onClick={() => setFilter(filter === s ? "ALL" : s)}
						>
							<span aria-hidden="true">{STATUS_ICON[s]}</span> {STATUS_LABEL[s]}{" "}
							<strong>{snap.counts[s.toLowerCase()] ?? 0}</strong>
						</button>
					))}
				</fieldset>
				{stale && (
					<Alert kind="warning">
						Data monitoring mungkin terlambat.{" "}
						<button type="button" className="btn btn-ghost" onClick={resync}>
							Sinkronkan
						</button>
					</Alert>
				)}
				<div className="form-row">
					<label className="field">
						<span>Cari peserta</span>
						<input
							value={query}
							onChange={(e) => setQuery(e.target.value)}
							placeholder="Nama atau NIS"
						/>
					</label>
					<label className="field">
						<span>Tampilkan</span>
						<select
							value={filter}
							onChange={(e) => setFilter(e.target.value as typeof filter)}
						>
							<option value="ALL">Semua</option>
							<option value="DISCONNECTED">Terputus</option>
							<option value="PAUSED">Dijeda</option>
							<option value="REVIEW">Perlu ditinjau</option>
							<option value="NOT_STARTED">Belum mulai</option>
							<option value="SUBMITTED">Selesai</option>
						</select>
					</label>
				</div>
				<p className="muted">
					Diperbarui {fmtTime(snap.server_now)} (waktu server)
				</p>
			</div>

			<div className="table-wrap">
				<table className="monitor">
					<thead>
						<tr>
							<th scope="col">NIS</th>
							<th scope="col">Peserta</th>
							<th scope="col">Terjawab</th>
							<th scope="col">Status</th>
							<th scope="col">Sisa</th>
							<th scope="col">Aksi</th>
						</tr>
					</thead>
					<tbody>
						{rows.map((p) => (
							<tr key={p.student_id}>
								<td data-label="NIS">{p.nis}</td>
								<td data-label="Peserta">
									{p.display_name}
									{p.tab_hidden > 0 && (
										<span
											className="chip chip-review"
											title="Indikator, bukan bukti kecurangan"
										>
											Perlu ditinjau ({p.tab_hidden})
										</span>
									)}
									{p.permit_pending && (
										<span className="chip">Izin pindah perangkat</span>
									)}
								</td>
								<td data-label="Terjawab">
									{p.attempt_id
										? `${p.answered_count}/${snap.total_count}`
										: "–"}
								</td>
								<td data-label="Status">
									<span className={`status status-${p.status.toLowerCase()}`}>
										<span aria-hidden="true">{STATUS_ICON[p.status]}</span>{" "}
										{STATUS_LABEL[p.status]}
									</span>
								</td>
								<td data-label="Sisa">{mmss(p.remaining_seconds)}</td>
								<td data-label="Aksi">
									{p.attempt_id && (
										<button
											type="button"
											className={`btn ${p.status === "DISCONNECTED" || p.status === "PAUSED" ? "btn-primary" : "btn-secondary"}`}
											onClick={() => open(p)}
										>
											{p.status === "DISCONNECTED" || p.status === "PAUSED"
												? "Tangani"
												: "Detail"}
										</button>
									)}
								</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>

			<Announcements
				examId={examId}
				items={snap.announcements}
				onSent={resync}
			/>

			<dialog
				ref={drawer}
				className="dialog drawer"
				aria-labelledby="h-incident"
			>
				{selected?.attempt_id && (
					<IncidentDrawer
						key={selected.attempt_id}
						participant={selected}
						onDone={() => {
							drawer.current?.close();
							resync();
						}}
						onClose={() => drawer.current?.close()}
					/>
				)}
			</dialog>
		</div>
	);
}

function IncidentDrawer({
	participant: p,
	onDone,
	onClose,
}: {
	participant: Participant;
	onDone: () => void;
	onClose: () => void;
}) {
	const [events, setEvents] = useState<EventRow[]>([]);
	const [reason, setReason] = useState("");
	const [minutes, setMinutes] = useState("5");
	const [busy, setBusy] = useState(false);
	const [result, setResult] = useState<{
		kind: "error" | "success";
		text: string;
	}>();
	const live = p.status !== "SUBMITTED";

	useEffect(() => {
		api<EventRow[]>(`/proctor/attempts/${p.attempt_id}/events`)
			.then(setEvents)
			.catch(() => {});
	}, [p.attempt_id]);

	async function act(path: string, body: Record<string, unknown>, ok: string) {
		setBusy(true);
		setResult(undefined);
		try {
			await api(`/proctor/attempts/${p.attempt_id}/${path}`, {
				json: { ...body, reason },
			});
			setResult({ kind: "success", text: ok });
			setReason("");
			setTimeout(onDone, 800);
		} catch (err) {
			setResult({ kind: "error", text: message(err) });
		} finally {
			setBusy(false);
		}
	}

	const reasonOk = reason.trim().length >= 10;
	return (
		<div className="stack">
			<h2 id="h-incident">
				{p.display_name} <span className="muted">({p.nis})</span>
			</h2>
			<p className="muted">
				{STATUS_LABEL[p.status]} · jeda terpakai {mmss(p.pause_consumed_sec)}{" "}
				dari 10:00 · sisa waktu {mmss(p.remaining_seconds)}
			</p>
			<section aria-labelledby="h-timeline">
				<h3 id="h-timeline">Riwayat</h3>
				{events.length === 0 ? (
					<p className="muted">Belum ada kejadian.</p>
				) : (
					<ul className="rules">
						{events.map((e, i) => (
							// biome-ignore lint/suspicious/noArrayIndexKey: daftar statis
							<li key={i}>
								{fmtTime(e.at)} · {EVENT_LABEL[e.kind] ?? e.kind}
								{e.seconds != null && ` (${mmss(e.seconds)})`}
								{e.reason && ` — ${e.reason}`}
							</li>
						))}
					</ul>
				)}
				<p className="muted">
					Pindah tab hanya indikator yang perlu diverifikasi langsung, bukan
					bukti kecurangan.
				</p>
			</section>
			{live ? (
				<>
					<label className="field">
						<span>Alasan tindakan (wajib, min. 10 karakter)</span>
						<textarea
							rows={2}
							value={reason}
							maxLength={500}
							onChange={(e) => setReason(e.target.value)}
						/>
					</label>
					<div className="form-row">
						<label className="field">
							<span>Tambah waktu (menit)</span>
							<input
								inputMode="numeric"
								value={minutes}
								onChange={(e) => setMinutes(e.target.value)}
							/>
						</label>
						<button
							type="button"
							className="btn btn-secondary"
							disabled={!reasonOk || busy}
							onClick={() =>
								act(
									"time-extensions",
									{ seconds: Math.round(Number(minutes) * 60) },
									"Waktu ditambahkan.",
								)
							}
						>
							Tambah waktu
						</button>
					</div>
					<div>
						<button
							type="button"
							className="btn btn-secondary"
							disabled={!reasonOk || busy}
							onClick={() =>
								act(
									"approve-device-switch",
									{},
									"Izin pindah perangkat aktif 5 menit. Minta siswa login di perangkat baru.",
								)
							}
						>
							Izinkan pindah perangkat / reset sesi
						</button>
					</div>
				</>
			) : (
				<p className="muted">Peserta sudah mengumpulkan; tidak ada tindakan.</p>
			)}
			{result && <Alert kind={result.kind}>{result.text}</Alert>}
			<div>
				<button type="button" className="btn btn-ghost" onClick={onClose}>
					Tutup
				</button>
			</div>
		</div>
	);
}

function Announcements({
	examId,
	items,
	onSent,
}: {
	examId: string;
	items: Snapshot["announcements"];
	onSent: () => void;
}) {
	const [text, setText] = useState("");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	async function send() {
		if (!window.confirm(`Kirim pengumuman ke semua peserta?\n\n${text}`))
			return;
		setBusy(true);
		setError("");
		try {
			await api(`/proctor/exams/${examId}/announcements`, {
				json: { message: text },
			});
			setText("");
			onSent();
		} catch (err) {
			setError(message(err));
		} finally {
			setBusy(false);
		}
	}
	return (
		<section className="card stack" aria-labelledby="h-announce">
			<h2 id="h-announce">Pengumuman</h2>
			<label className="field">
				<span>Pesan untuk semua peserta</span>
				<textarea
					rows={2}
					maxLength={500}
					value={text}
					onChange={(e) => setText(e.target.value)}
				/>
			</label>
			<Alert kind="error">{error}</Alert>
			<div>
				<button
					type="button"
					className="btn btn-primary"
					disabled={!text.trim() || busy}
					onClick={send}
				>
					Kirim pengumuman
				</button>
			</div>
			{items.length > 0 && (
				<ul className="rules">
					{items.map((a) => (
						<li key={a.issued_at}>
							{fmtTime(a.issued_at)} · {a.sender}: {a.message}
						</li>
					))}
				</ul>
			)}
		</section>
	);
}
