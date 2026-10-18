import { type FormEvent, useState } from "react";
import { ApiError, api, EXPIRED_FLAG, type Me, setCsrf } from "./api";

function takeExpiredFlag(): boolean {
	try {
		const flag = sessionStorage.getItem(EXPIRED_FLAG) === "1";
		sessionStorage.removeItem(EXPIRED_FLAG);
		return flag;
	} catch {
		return false;
	}
}

export function Login({ onLogin }: { onLogin: (me: Me) => void }) {
	const [expired] = useState(takeExpiredFlag);
	const [error, setError] = useState("");
	const [busy, setBusy] = useState(false);
	const [showPassword, setShowPassword] = useState(false);

	async function submit(e: FormEvent<HTMLFormElement>) {
		e.preventDefault();
		const form = new FormData(e.currentTarget);
		setBusy(true);
		setError("");
		try {
			const res = await api<{ user: Me; csrf_token: string }>("/auth/login", {
				json: {
					username: String(form.get("username") ?? ""),
					password: String(form.get("password") ?? ""),
				},
			});
			setCsrf(res.csrf_token);
			onLogin(res.user);
		} catch (err) {
			setError(
				err instanceof ApiError ? err.message : "Terjadi kesalahan. Coba lagi.",
			);
			setBusy(false);
		}
	}

	return (
		<main className="login">
			<h1>LocalCBT</h1>
			<p className="muted">Masuk untuk memulai.</p>
			{expired && (
				<p className="alert alert-warning" role="status">
					Sesi berakhir. Silakan masuk kembali.
				</p>
			)}
			<form onSubmit={submit} className="card stack" noValidate>
				<label className="field">
					<span>NIS / Username</span>
					<input
						name="username"
						autoComplete="username"
						autoCapitalize="none"
						spellCheck={false}
						required
						maxLength={64}
					/>
				</label>
				<label className="field">
					<span>Kata sandi</span>
					<span className="input-row">
						<input
							name="password"
							type={showPassword ? "text" : "password"}
							autoComplete="current-password"
							required
						/>
						<button
							type="button"
							className="btn btn-ghost"
							aria-pressed={showPassword}
							onClick={() => setShowPassword((v) => !v)}
						>
							{showPassword ? "Sembunyikan" : "Tampilkan"}
						</button>
					</span>
				</label>
				{error && (
					<p className="alert alert-error" role="alert">
						{error}
					</p>
				)}
				<button type="submit" className="btn btn-primary" disabled={busy}>
					{busy ? "Memeriksa…" : "Masuk"}
				</button>
			</form>
		</main>
	);
}
