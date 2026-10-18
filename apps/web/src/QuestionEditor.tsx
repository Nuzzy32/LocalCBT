import { type FormEvent, useId, useState } from "react";
import { api } from "./api";
import { Alert, message } from "./ui";

export type QType = "SINGLE_CHOICE" | "MULTIPLE_CHOICE" | "CATEGORY_CHOICE";
type Option = { id?: string; text: string; is_correct: boolean };
type Statement = { id?: string; text: string; correct_value: boolean };
export type Question = {
	id: string;
	type: QType;
	stem: string;
	weight: number;
	version: number;
	stimulus_id: string | null;
	stimulus: string | null;
	stimulus_image_url: string | null;
	media_asset_id: string | null;
	image_url: string | null;
	options: Option[];
	statements: Statement[];
};
export type StudentQuestion = Pick<
	Question,
	| "id"
	| "type"
	| "stem"
	| "weight"
	| "stimulus"
	| "stimulus_image_url"
	| "image_url"
> & {
	options: { id: string; text: string }[];
	statements: { id: string; text: string }[];
};
export type Stimulus = {
	id: string;
	body_text: string | null;
	image_url: string | null;
};

export const TYPE_LABEL: Record<QType, string> = {
	SINGLE_CHOICE: "Pilihan Ganda",
	MULTIPLE_CHOICE: "Pilihan Ganda Kompleks",
	CATEGORY_CHOICE: "Benar/Salah per Pernyataan",
};
export const LETTER = "ABCDEFGHIJ";

export type Answer =
	| { type: "SINGLE_CHOICE"; selected_option_id: string }
	| { type: "MULTIPLE_CHOICE"; selected_option_ids: string[] }
	| {
			type: "CATEGORY_CHOICE";
			choices: { statement_id: string; value: boolean }[];
	  };

/** Tampilan soal seperti di layar siswa (tanpa kunci). Dipakai pratinjau guru, ujian, dan
 * pembahasan. Terkontrol bila `onChange`/`disabled` diberikan; tanpa itu (pratinjau) bebas. */
export function StudentQuestionView({
	q,
	number,
	total,
	value,
	onChange,
	disabled = false,
}: {
	q: StudentQuestion;
	number: number;
	total: number;
	value?: Answer | null;
	onChange?: (answer: Answer | null) => void;
	disabled?: boolean;
}) {
	const name = useId();
	const controlled = onChange !== undefined || disabled;
	const selected =
		value?.type === "SINGLE_CHOICE"
			? [value.selected_option_id]
			: value?.type === "MULTIPLE_CHOICE"
				? value.selected_option_ids
				: [];
	const choices =
		value?.type === "CATEGORY_CHOICE"
			? Object.fromEntries(value.choices.map((c) => [c.statement_id, c.value]))
			: {};
	const checked = (on: boolean) => (controlled ? on : undefined);

	function pickOption(id: string, on: boolean) {
		if (q.type === "SINGLE_CHOICE") {
			onChange?.({ type: "SINGLE_CHOICE", selected_option_id: id });
			return;
		}
		const ids = on ? [...selected, id] : selected.filter((x) => x !== id);
		onChange?.(
			ids.length ? { type: "MULTIPLE_CHOICE", selected_option_ids: ids } : null,
		);
	}

	function pickStatement(id: string, v: boolean) {
		const next = { ...choices, [id]: v };
		onChange?.({
			type: "CATEGORY_CHOICE",
			choices: Object.entries(next).map(([statement_id, val]) => ({
				statement_id,
				value: val,
			})),
		});
	}

	return (
		<article className="card stack question">
			<h3>
				Soal {number} dari {total}
			</h3>
			{(q.stimulus || q.stimulus_image_url) && (
				<div className="stimulus">
					{q.stimulus_image_url && (
						<img src={q.stimulus_image_url} alt="Gambar stimulus" />
					)}
					{q.stimulus && <p className="pre">{q.stimulus}</p>}
				</div>
			)}
			{q.image_url && <img src={q.image_url} alt="Gambar soal" />}
			<p className="pre stem">{q.stem}</p>
			{q.type === "CATEGORY_CHOICE" ? (
				<div className="stack">
					{q.statements.map((s) => (
						<fieldset key={s.id} className="statement" disabled={disabled}>
							<legend>{s.text}</legend>
							{[true, false].map((v) => (
								<label key={String(v)} className="choice">
									<input
										type="radio"
										name={`${name}-${s.id}`}
										checked={checked(choices[s.id] === v)}
										onChange={() => pickStatement(s.id, v)}
									/>{" "}
									{v ? "Benar" : "Salah"}
								</label>
							))}
						</fieldset>
					))}
				</div>
			) : (
				<fieldset className="stack" disabled={disabled}>
					<legend className="muted">
						{q.type === "MULTIPLE_CHOICE"
							? "Pilih semua jawaban yang benar."
							: "Pilih satu jawaban."}
					</legend>
					{q.options.map((o, i) => (
						<label key={o.id} className="choice">
							<input
								type={q.type === "MULTIPLE_CHOICE" ? "checkbox" : "radio"}
								name={name}
								checked={checked(selected.includes(o.id))}
								onChange={(e) => pickOption(o.id, e.target.checked)}
							/>
							<span>
								{LETTER[i]}. {o.text}
							</span>
						</label>
					))}
				</fieldset>
			)}
		</article>
	);
}

type Draft = {
	type: QType;
	stem: string;
	weight: string;
	stimulus_id: string;
	media_asset_id: string | null;
	image_url: string | null;
	options: Option[];
	statements: Statement[];
};

const blankOptions = () =>
	Array.from({ length: 4 }, () => ({ text: "", is_correct: false }));
const blankStatements = () =>
	Array.from({ length: 2 }, () => ({ text: "", correct_value: true }));

function toDraft(q: Question | null): Draft {
	return {
		type: q?.type ?? "SINGLE_CHOICE",
		stem: q?.stem ?? "",
		weight: String(q?.weight ?? 1),
		stimulus_id: q?.stimulus_id ?? "",
		media_asset_id: q?.media_asset_id ?? null,
		image_url: q?.image_url ?? null,
		options: q?.options.length ? q.options : blankOptions(),
		statements: q?.statements.length ? q.statements : blankStatements(),
	};
}

export function QuestionEditor({
	bankId,
	stimuli,
	initial,
	onSaved,
	onCancel,
}: {
	bankId: string;
	stimuli: Stimulus[];
	initial: Question | null;
	onSaved: () => void;
	onCancel: () => void;
}) {
	const [d, setD] = useState<Draft>(() => toDraft(initial));
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [showPreview, setShowPreview] = useState(false);
	const update = (patch: Partial<Draft>) =>
		setD((prev) => ({ ...prev, ...patch }));
	const isCategory = d.type === "CATEGORY_CHOICE";

	function changeType(type: QType) {
		const filled =
			d.stem.trim() !== "" ||
			d.options.some((o) => o.text.trim()) ||
			d.statements.some((s) => s.text.trim());
		if (
			filled &&
			!window.confirm(
				"Mengubah jenis soal akan menyesuaikan bentuk kunci jawaban. Lanjutkan?",
			)
		) {
			return;
		}
		// PG tunggal hanya boleh satu kunci: pertahankan kunci pertama saja.
		let seen = false;
		const options =
			type === "SINGLE_CHOICE"
				? d.options.map((o) => {
						const keep = o.is_correct && !seen;
						seen ||= keep;
						return { ...o, is_correct: keep };
					})
				: d.options;
		update({ type, options });
	}

	function setOption(i: number, patch: Partial<Option>) {
		update({
			options: d.options.map((o, j) => {
				if (j === i) return { ...o, ...patch };
				// Radio PG: memilih satu kunci melepas kunci lain.
				return patch.is_correct && d.type === "SINGLE_CHOICE"
					? { ...o, is_correct: false }
					: o;
			}),
		});
	}

	function setStatement(i: number, patch: Partial<Statement>) {
		update({
			statements: d.statements.map((s, j) =>
				j === i ? { ...s, ...patch } : s,
			),
		});
	}

	async function uploadImage(file: File | undefined) {
		if (!file) return;
		const form = new FormData();
		form.set("file", file);
		setError("");
		try {
			const res = await api<{ id: string; url: string }>("/media", { form });
			update({ media_asset_id: res.id, image_url: res.url });
		} catch (err) {
			setError(message(err));
		}
	}

	const payload = () => ({
		type: d.type,
		stem: d.stem,
		weight: Number(d.weight.replace(",", ".")),
		stimulus_id: d.stimulus_id || null,
		media_asset_id: d.media_asset_id,
		options: isCategory
			? []
			: d.options
					.filter((o) => o.text.trim())
					.map(({ text, is_correct }) => ({ text, is_correct })),
		statements: isCategory
			? d.statements
					.filter((s) => s.text.trim())
					.map(({ text, correct_value }) => ({ text, correct_value }))
			: [],
	});

	async function save(e: FormEvent) {
		e.preventDefault();
		setBusy(true);
		setError("");
		try {
			const base = `/question-banks/${bankId}/questions`;
			await api(initial ? `${base}/${initial.id}` : base, {
				method: initial ? "PUT" : "POST",
				json: payload(),
			});
			onSaved();
		} catch (err) {
			setError(message(err));
			setBusy(false);
		}
	}

	const stimulus = stimuli.find((s) => s.id === d.stimulus_id);
	const p = payload();
	const previewQ: StudentQuestion = {
		id: "draft",
		type: d.type,
		stem: d.stem || "(pertanyaan kosong)",
		weight: p.weight,
		stimulus: stimulus?.body_text ?? null,
		stimulus_image_url: stimulus?.image_url ?? null,
		image_url: d.image_url,
		options: p.options.map((o, i) => ({ id: String(i), text: o.text })),
		statements: p.statements.map((s, i) => ({ id: String(i), text: s.text })),
	};

	return (
		<form onSubmit={save} className="card stack" noValidate>
			<h2>
				{initial ? `Edit soal (versi ${initial.version})` : "Tambah soal"}
			</h2>
			<div className="form-row">
				<label className="field">
					<span>Jenis soal</span>
					<select
						value={d.type}
						onChange={(e) => changeType(e.target.value as QType)}
					>
						{Object.entries(TYPE_LABEL).map(([value, label]) => (
							<option key={value} value={value}>
								{label}
							</option>
						))}
					</select>
				</label>
				<label className="field">
					<span>Bobot</span>
					<input
						inputMode="decimal"
						value={d.weight}
						onChange={(e) => update({ weight: e.target.value })}
						required
					/>
				</label>
				<label className="field">
					<span>Stimulus bersama</span>
					<select
						value={d.stimulus_id}
						onChange={(e) => update({ stimulus_id: e.target.value })}
					>
						<option value="">Tidak ada</option>
						{stimuli.map((s) => (
							<option key={s.id} value={s.id}>
								{(s.body_text ?? "Gambar").slice(0, 60)}
							</option>
						))}
					</select>
				</label>
			</div>

			<label className="field">
				<span>Pertanyaan</span>
				<textarea
					rows={4}
					value={d.stem}
					onChange={(e) => update({ stem: e.target.value })}
					required
				/>
			</label>

			<div className="form-row">
				<label className="field">
					<span>Gambar soal (PNG/JPEG/WebP, maks. 2 MB)</span>
					<input
						type="file"
						accept="image/png,image/jpeg,image/webp"
						onChange={(e) => uploadImage(e.target.files?.[0])}
					/>
				</label>
				{d.image_url && (
					<div className="thumb">
						<img src={d.image_url} alt="Gambar soal terpilih" />
						<button
							type="button"
							className="btn btn-ghost"
							onClick={() => update({ media_asset_id: null, image_url: null })}
						>
							Hapus gambar
						</button>
					</div>
				)}
			</div>

			{isCategory ? (
				<fieldset className="stack">
					<legend>Pernyataan dan kunci Benar/Salah</legend>
					{d.statements.map((s, i) => (
						// biome-ignore lint/suspicious/noArrayIndexKey: baris draf tanpa id stabil
						<div key={i} className="option-row">
							<input
								aria-label={`Pernyataan ${i + 1}`}
								value={s.text}
								onChange={(e) => setStatement(i, { text: e.target.value })}
							/>
							<label className="check">
								<input
									type="radio"
									name={`st-${i}`}
									checked={s.correct_value}
									onChange={() => setStatement(i, { correct_value: true })}
								/>
								Benar
							</label>
							<label className="check">
								<input
									type="radio"
									name={`st-${i}`}
									checked={!s.correct_value}
									onChange={() => setStatement(i, { correct_value: false })}
								/>
								Salah
							</label>
							<button
								type="button"
								className="btn btn-ghost"
								disabled={d.statements.length <= 2}
								onClick={() =>
									update({ statements: d.statements.filter((_, j) => j !== i) })
								}
							>
								Hapus
							</button>
						</div>
					))}
					<div>
						<button
							type="button"
							className="btn btn-secondary"
							disabled={d.statements.length >= 20}
							onClick={() =>
								update({
									statements: [
										...d.statements,
										{ text: "", correct_value: true },
									],
								})
							}
						>
							Tambah pernyataan
						</button>
					</div>
				</fieldset>
			) : (
				<fieldset className="stack">
					<legend>
						Opsi jawaban —{" "}
						{d.type === "MULTIPLE_CHOICE"
							? "centang semua kunci yang benar"
							: "pilih satu kunci"}
					</legend>
					{d.options.map((o, i) => (
						// biome-ignore lint/suspicious/noArrayIndexKey: baris draf tanpa id stabil
						<div key={i} className="option-row">
							<span className="letter">{LETTER[i]}</span>
							<input
								aria-label={`Opsi ${LETTER[i]}`}
								value={o.text}
								onChange={(e) => setOption(i, { text: e.target.value })}
							/>
							<label className="check">
								<input
									type={d.type === "MULTIPLE_CHOICE" ? "checkbox" : "radio"}
									name="key"
									checked={o.is_correct}
									onChange={(e) =>
										setOption(i, { is_correct: e.target.checked })
									}
								/>
								Kunci
							</label>
							<button
								type="button"
								className="btn btn-ghost"
								disabled={d.options.length <= 2}
								onClick={() =>
									update({ options: d.options.filter((_, j) => j !== i) })
								}
							>
								Hapus
							</button>
						</div>
					))}
					<div>
						<button
							type="button"
							className="btn btn-secondary"
							disabled={d.options.length >= 10}
							onClick={() =>
								update({
									options: [...d.options, { text: "", is_correct: false }],
								})
							}
						>
							Tambah opsi
						</button>
					</div>
				</fieldset>
			)}

			<Alert kind="error">{error}</Alert>
			<div className="form-row">
				<button type="submit" className="btn btn-primary" disabled={busy}>
					{busy ? "Menyimpan…" : "Simpan soal"}
				</button>
				<button
					type="button"
					className="btn btn-secondary"
					aria-expanded={showPreview}
					onClick={() => setShowPreview((v) => !v)}
				>
					{showPreview ? "Tutup pratinjau" : "Pratinjau siswa"}
				</button>
				<button type="button" className="btn btn-ghost" onClick={onCancel}>
					Batal
				</button>
			</div>
			{showPreview && <StudentQuestionView q={previewQ} number={1} total={1} />}
		</form>
	);
}
