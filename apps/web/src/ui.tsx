import { type FormEvent, type ReactNode, useState } from "react";
import { ApiError, api } from "./api";

export const message = (err: unknown) =>
	err instanceof ApiError ? err.message : "Terjadi kesalahan. Coba lagi.";

/** Pindah halaman SPA tanpa reload; App mendengarkan popstate. */
export function navigate(to: string) {
	window.history.pushState(null, "", to);
	window.dispatchEvent(new PopStateEvent("popstate"));
}

export function Alert({
	kind,
	children,
}: {
	kind: "error" | "warning" | "success";
	children: ReactNode;
}) {
	if (!children) return null;
	return (
		<p
			className={`alert alert-${kind}`}
			role={kind === "error" ? "alert" : "status"}
		>
			{children}
		</p>
	);
}

/** Form dengan state busy/error/sukses standar. `run` mengembalikan pesan sukses. */
export function ActionForm({
	label,
	run,
	children,
}: {
	label: string;
	run: (form: FormData) => Promise<string | undefined>;
	children: ReactNode;
}) {
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [done, setDone] = useState("");

	async function submit(e: FormEvent<HTMLFormElement>) {
		e.preventDefault();
		const el = e.currentTarget;
		setBusy(true);
		setError("");
		setDone("");
		try {
			setDone((await run(new FormData(el))) ?? "");
			el.reset();
		} catch (err) {
			setError(message(err));
		} finally {
			setBusy(false);
		}
	}

	return (
		<form onSubmit={submit} className="stack">
			<div className="form-row">{children}</div>
			<Alert kind="error">{error}</Alert>
			<Alert kind="success">{done}</Alert>
			<div>
				<button type="submit" className="btn btn-primary" disabled={busy}>
					{busy ? "Menyimpan…" : label}
				</button>
			</div>
		</form>
	);
}

export function Field({
	label,
	...input
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
	return (
		<label className="field">
			<span>{label}</span>
			<input required {...input} />
		</label>
	);
}

export function Select({
	label,
	name,
	options,
}: {
	label: string;
	name: string;
	options: { value: string; label: string }[];
}) {
	return (
		<label className="field">
			<span>{label}</span>
			<select name={name} required defaultValue="">
				<option value="" disabled>
					Pilih…
				</option>
				{options.map((o) => (
					<option key={o.value} value={o.value}>
						{o.label}
					</option>
				))}
			</select>
		</label>
	);
}

type ImportPreview = {
	preview_id: string;
	total_rows: number;
	valid_rows: number;
	errors: { row_number: number; field: string; message: string }[];
};

/** Unggah → periksa (preview + error per baris) → simpan. Dipakai import siswa & soal. */
export function ImportPanel<T>({
	previewPath,
	commitPath,
	accept,
	fileLabel,
	rowLabel,
	help,
	onCommitted,
}: {
	previewPath: string;
	commitPath: string;
	accept: string;
	fileLabel: string;
	rowLabel: string;
	help: ReactNode;
	onCommitted: (result: T) => ReactNode;
}) {
	const [preview, setPreview] = useState<ImportPreview | null>(null);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [result, setResult] = useState<ReactNode>(null);

	async function upload(e: FormEvent<HTMLFormElement>) {
		e.preventDefault();
		setBusy(true);
		setError("");
		setPreview(null);
		setResult(null);
		try {
			setPreview(
				await api<ImportPreview>(previewPath, {
					form: new FormData(e.currentTarget),
				}),
			);
		} catch (err) {
			setError(message(err));
		} finally {
			setBusy(false);
		}
	}

	async function commit() {
		if (!preview) return;
		setBusy(true);
		setError("");
		try {
			const res = await api<T>(commitPath, {
				json: { preview_id: preview.preview_id, confirm: true },
			});
			setPreview(null);
			setResult(onCommitted(res));
		} catch (err) {
			setError(message(err));
		} finally {
			setBusy(false);
		}
	}

	return (
		<div className="stack">
			<div className="muted">{help}</div>
			<form onSubmit={upload} className="form-row">
				<label className="field">
					<span>{fileLabel}</span>
					<input type="file" name="file" accept={accept} required />
				</label>
				<button type="submit" className="btn btn-secondary" disabled={busy}>
					{busy && !preview ? "Memeriksa…" : "Periksa berkas"}
				</button>
			</form>
			<Alert kind="error">{error}</Alert>
			{preview && (
				<div className="stack" aria-live="polite">
					<p>
						{preview.valid_rows} dari {preview.total_rows} {rowLabel} valid.
					</p>
					{preview.errors.length > 0 ? (
						<>
							<Alert kind="warning">
								Ada {preview.errors.length} masalah. Perbaiki berkas lalu
								periksa ulang; tidak ada data yang disimpan sebelum semua{" "}
								{rowLabel} valid.
							</Alert>
							<div className="table-wrap">
								<table>
									<thead>
										<tr>
											<th scope="col">
												{rowLabel === "soal" ? "Soal ke" : "Baris"}
											</th>
											<th scope="col">Kolom</th>
											<th scope="col">Masalah</th>
										</tr>
									</thead>
									<tbody>
										{preview.errors.map((e, i) => (
											// biome-ignore lint/suspicious/noArrayIndexKey: daftar statis per preview
											<tr key={i}>
												<td>{e.row_number}</td>
												<td>{e.field}</td>
												<td>{e.message}</td>
											</tr>
										))}
									</tbody>
								</table>
							</div>
						</>
					) : (
						<div>
							<button
								type="button"
								className="btn btn-primary"
								onClick={commit}
								disabled={busy}
							>
								{busy
									? "Menyimpan…"
									: `Simpan ${preview.valid_rows} ${rowLabel}`}
							</button>
						</div>
					)}
				</div>
			)}
			{result}
		</div>
	);
}
