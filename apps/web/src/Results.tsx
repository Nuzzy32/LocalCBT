import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Alert, message, navigate } from "./ui";

type Row = {
	student_id: string;
	nis: string;
	display_name: string;
	class_codes: string | null;
	status: "NOT_STARTED" | "IN_PROGRESS" | "PAUSED" | "SUBMITTED" | "GRADED";
	score: number | null;
	max_score: number | null;
	submit_reason: "STUDENT" | "DEADLINE" | null;
};
type Results = {
	title: string;
	visibility: "TEACHER_ONLY" | "IMMEDIATE" | "AFTER_PUBLICATION";
	results_published_at: string | null;
	rows: Row[];
};

const STATUS: Record<Row["status"], string> = {
	NOT_STARTED: "Belum mulai",
	IN_PROGRESS: "Mengerjakan",
	PAUSED: "Dijeda",
	SUBMITTED: "Penilaian tertunda",
	GRADED: "Dinilai",
};

export function ExamResults({ examId }: { examId: string }) {
	const [data, setData] = useState<Results | null>(null);
	const [error, setError] = useState("");
	const [notice, setNotice] = useState("");
	const base = `/teacher/exams/${examId}`;
	const load = useCallback(
		() =>
			api<Results>(`${base}/results`)
				.then(setData)
				.catch((err) => setError(message(err))),
		[base],
	);
	useEffect(() => {
		load();
	}, [load]);

	async function post(path: string, ok: string) {
		setError("");
		try {
			await api(`${base}/${path}`, { method: "POST" });
			setNotice(ok);
			load();
		} catch (err) {
			setError(message(err));
		}
	}

	if (!data)
		return error ? (
			<Alert kind="error">{error}</Alert>
		) : (
			<p className="muted">Memuat…</p>
		);
	const pending = data.rows.filter((r) => r.status === "SUBMITTED").length;
	const graded = data.rows.filter((r) => r.status === "GRADED");

	return (
		<div className="stack-lg">
			<div>
				<button
					type="button"
					className="btn btn-ghost"
					onClick={() => navigate(`/teacher/exams/${examId}`)}
				>
					← Kembali ke ujian
				</button>
			</div>
			<section className="card stack" aria-labelledby="h-results">
				<h2 id="h-results">Hasil: {data.title}</h2>
				<p className="muted">
					{graded.length} dinilai dari {data.rows.length} peserta.{" "}
					{data.visibility === "TEACHER_ONLY"
						? "Nilai hanya untuk guru (kebijakan ujian)."
						: data.visibility === "IMMEDIATE"
							? "Siswa melihat nilai langsung setelah dinilai."
							: data.results_published_at
								? `Nilai dipublikasikan ke siswa ${new Date(data.results_published_at).toLocaleString("id-ID")}.`
								: "Nilai belum dipublikasikan ke siswa."}{" "}
					Pembahasan diatur terpisah di halaman ujian.
				</p>
				<Alert kind="success">{notice}</Alert>
				<Alert kind="error">{error}</Alert>
				<div className="form-row">
					{data.visibility === "AFTER_PUBLICATION" &&
						(data.results_published_at ? (
							<button
								type="button"
								className="btn btn-secondary"
								onClick={() =>
									post("results/unpublish", "Publikasi nilai ditarik.")
								}
							>
								Tarik publikasi nilai
							</button>
						) : (
							<button
								type="button"
								className="btn btn-primary"
								onClick={() => {
									if (window.confirm("Publikasikan nilai ke siswa sekarang?"))
										post("results/publish", "Nilai dipublikasikan ke siswa.");
								}}
							>
								Publikasikan nilai
							</button>
						))}
					<a
						className="btn btn-secondary link-btn"
						href={`/api/v1${base}/results/export`}
						download
					>
						Unduh XLSX
					</a>
					{pending > 0 && (
						<button
							type="button"
							className="btn btn-secondary"
							onClick={() => post("regrade", "Penilaian ulang selesai.")}
						>
							Nilai ulang {pending} yang tertunda
						</button>
					)}
				</div>
			</section>
			<div className="table-wrap">
				<table>
					<thead>
						<tr>
							<th scope="col">NIS</th>
							<th scope="col">Nama</th>
							<th scope="col">Kelas</th>
							<th scope="col">Status</th>
							<th scope="col">Nilai</th>
						</tr>
					</thead>
					<tbody>
						{data.rows.map((r) => (
							<tr key={r.student_id}>
								<td>{r.nis}</td>
								<td>{r.display_name}</td>
								<td>{r.class_codes}</td>
								<td>
									{STATUS[r.status]}
									{r.submit_reason === "DEADLINE" && " (waktu habis)"}
								</td>
								<td className="num">
									{r.score != null ? `${r.score} / ${r.max_score}` : "–"}
								</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
		</div>
	);
}
