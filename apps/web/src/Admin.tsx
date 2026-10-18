import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ActionForm, Alert, Field, ImportPanel, message, Select } from "./ui";

type Klass = { id: string; code: string; label: string; academic_year: string };
type Subject = { id: string; code: string; name: string };
type Staff = {
	id: string;
	username: string;
	display_name: string;
	roles: string[];
};
type Credential = {
	nis: string;
	name: string;
	class: string;
	password: string;
};

// Sel CSV diawali = + - @ dieksekusi Excel sebagai rumus: beri prefiks petik.
function csvCell(value: string) {
	const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
	return `"${safe.replaceAll('"', '""')}"`;
}

function downloadCredentials(rows: Credential[]) {
	const lines = [
		["NIS", "Nama", "Kelas", "Kata sandi"],
		...rows.map((r) => [r.nis, r.name, r.class, r.password]),
	].map((cols) => cols.map(csvCell).join(","));
	const url = URL.createObjectURL(
		new Blob([`﻿${lines.join("\r\n")}`], { type: "text/csv" }),
	);
	const a = document.createElement("a");
	a.href = url;
	a.download = "kredensial-siswa.csv";
	a.click();
	URL.revokeObjectURL(url);
}

function StudentImport({ onDone }: { onDone: () => void }) {
	return (
		<ImportPanel<{ credentials: Credential[] }>
			previewPath="/admin/students/import/preview"
			commitPath="/admin/students/import/commit"
			accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
			fileLabel="Berkas siswa"
			rowLabel="baris"
			help={
				<p className="muted">
					Berkas .xlsx, baris pertama berisi kolom <b>NIS</b>, <b>Nama</b>,{" "}
					<b>Kelas</b> (kode kelas aktif). Format kolom NIS sebagai teks agar
					nol di depan tidak hilang. Maksimal 2 MB / 2000 siswa.
				</p>
			}
			onCommitted={({ credentials }) => {
				downloadCredentials(credentials);
				onDone();
				return (
					<Alert kind="success">
						{credentials.length} siswa tersimpan dan berkas kredensial sudah
						diunduh. Simpan dengan aman: kata sandi tidak bisa ditampilkan lagi
						setelah halaman ini ditutup.{" "}
						<button
							type="button"
							className="btn btn-ghost"
							onClick={() => downloadCredentials(credentials)}
						>
							Unduh lagi
						</button>
					</Alert>
				);
			}}
		/>
	);
}

export function Admin() {
	const [classes, setClasses] = useState<Klass[]>([]);
	const [subjects, setSubjects] = useState<Subject[]>([]);
	const [staff, setStaff] = useState<Staff[]>([]);
	const [loadError, setLoadError] = useState("");
	const [newPassword, setNewPassword] = useState<{
		username: string;
		password: string;
	} | null>(null);

	const reload = useCallback(() => {
		Promise.all([
			api<Klass[]>("/admin/classes"),
			api<Subject[]>("/admin/subjects"),
			api<Staff[]>("/admin/staff"),
		])
			.then(([c, s, st]) => {
				setClasses(c);
				setSubjects(s);
				setStaff(st);
				setLoadError("");
			})
			.catch((err) => setLoadError(message(err)));
	}, []);
	useEffect(reload, [reload]);

	return (
		<div className="stack-lg">
			{loadError && (
				<p className="alert alert-error" role="alert">
					{loadError}
				</p>
			)}

			<section className="card stack" aria-labelledby="h-classes">
				<h2 id="h-classes">Kelas</h2>
				{classes.length === 0 ? (
					<p className="muted">Belum ada kelas.</p>
				) : (
					<ul className="chips">
						{classes.map((c) => (
							<li key={c.id}>
								{c.code} · {c.label} · {c.academic_year}
							</li>
						))}
					</ul>
				)}
				<ActionForm
					label="Tambah kelas"
					run={async (f) => {
						await api("/admin/classes", {
							json: {
								code: f.get("code"),
								label: f.get("label"),
								academic_year: f.get("academic_year"),
							},
						});
						reload();
						return "Kelas ditambahkan.";
					}}
				>
					<Field label="Kode" name="code" placeholder="IX-A" maxLength={32} />
					<Field label="Nama kelas" name="label" placeholder="Kelas IX A" />
					<Field
						label="Tahun ajaran"
						name="academic_year"
						placeholder="2026/2027"
						pattern="\d{4}/\d{4}"
					/>
				</ActionForm>
			</section>

			<section className="card stack" aria-labelledby="h-subjects">
				<h2 id="h-subjects">Mata pelajaran</h2>
				{subjects.length === 0 ? (
					<p className="muted">Belum ada mata pelajaran.</p>
				) : (
					<ul className="chips">
						{subjects.map((s) => (
							<li key={s.id}>
								{s.code} · {s.name}
							</li>
						))}
					</ul>
				)}
				<ActionForm
					label="Tambah mapel"
					run={async (f) => {
						await api("/admin/subjects", {
							json: { code: f.get("code"), name: f.get("name") },
						});
						reload();
						return "Mata pelajaran ditambahkan.";
					}}
				>
					<Field label="Kode" name="code" placeholder="MTK" maxLength={32} />
					<Field label="Nama" name="name" placeholder="Matematika" />
				</ActionForm>
			</section>

			<section className="card stack" aria-labelledby="h-staff">
				<h2 id="h-staff">Guru & pengawas</h2>
				{staff.length > 0 && (
					<div className="table-wrap">
						<table>
							<thead>
								<tr>
									<th scope="col">Nama</th>
									<th scope="col">Username</th>
									<th scope="col">Peran</th>
								</tr>
							</thead>
							<tbody>
								{staff.map((s) => (
									<tr key={s.id}>
										<td>{s.display_name}</td>
										<td>{s.username}</td>
										<td>{s.roles.join(", ")}</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				)}
				<ActionForm
					label="Buat akun"
					run={async (f) => {
						const res = await api<{
							username: string;
							temporary_password: string;
						}>("/admin/staff", {
							json: {
								username: f.get("username"),
								display_name: f.get("display_name"),
								roles: f.getAll("roles"),
							},
						});
						setNewPassword({
							username: res.username,
							password: res.temporary_password,
						});
						reload();
						return undefined;
					}}
				>
					<Field label="Username" name="username" autoCapitalize="none" />
					<Field label="Nama lengkap" name="display_name" />
					<fieldset className="field">
						<legend>Peran</legend>
						<label className="check">
							<input type="checkbox" name="roles" value="TEACHER" /> Guru
						</label>
						<label className="check">
							<input type="checkbox" name="roles" value="PROCTOR" /> Pengawas
						</label>
					</fieldset>
				</ActionForm>
				{newPassword && (
					<div className="alert alert-success" role="status">
						Akun <b>{newPassword.username}</b> dibuat. Kata sandi sementara:{" "}
						<code className="secret">{newPassword.password}</code>
						<br />
						Catat sekarang: kata sandi ini hanya ditampilkan sekali.{" "}
						<button
							type="button"
							className="btn btn-ghost"
							onClick={() => setNewPassword(null)}
						>
							Sudah dicatat
						</button>
					</div>
				)}
			</section>

			<section className="card stack" aria-labelledby="h-assign">
				<h2 id="h-assign">Penugasan mengajar</h2>
				<ActionForm
					label="Tugaskan"
					run={async (f) => {
						await api("/admin/teaching-assignments", {
							json: {
								teacher_id: f.get("teacher_id"),
								class_id: f.get("class_id"),
								subject_id: f.get("subject_id"),
							},
						});
						return "Guru ditugaskan.";
					}}
				>
					<Select
						label="Guru"
						name="teacher_id"
						options={staff
							.filter((s) => s.roles.includes("TEACHER"))
							.map((s) => ({ value: s.id, label: s.display_name }))}
					/>
					<Select
						label="Kelas"
						name="class_id"
						options={classes.map((c) => ({
							value: c.id,
							label: `${c.code} (${c.academic_year})`,
						}))}
					/>
					<Select
						label="Mapel"
						name="subject_id"
						options={subjects.map((s) => ({ value: s.id, label: s.name }))}
					/>
				</ActionForm>
			</section>

			<section className="card stack" aria-labelledby="h-import">
				<h2 id="h-import">Import siswa</h2>
				<StudentImport onDone={reload} />
			</section>
		</div>
	);
}
