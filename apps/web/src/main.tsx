import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Admin } from "./Admin";
import { ApiError, api, type Me, ROLE_HOME, setCsrf } from "./api";
import { Login } from "./Login";
import { TeacherPage } from "./Teacher";
import "./tokens.css";

function homeFor(me: Me): string {
	return ROLE_HOME.find(([role]) => me.roles.includes(role))?.[1] ?? "/";
}

// "/teacher/questions/x" → "/teacher": area milik satu role.
const section = (path: string) => `/${path.split("/")[1] ?? ""}`;

function allowed(me: Me, path: string): boolean {
	return ROLE_HOME.some(
		([role, home]) => home === section(path) && me.roles.includes(role),
	);
}

const TITLES: Record<string, string> = {
	"/admin": "Administrasi",
	"/teacher": "Bank soal",
	"/proctor": "Pengawasan",
	"/student": "Ujian saya",
};

// Router minimal: satu halaman per role. Otorisasi sebenarnya tetap di server.
function App() {
	const [me, setMe] = useState<Me | null | undefined>(undefined);
	const [path, setPath] = useState(window.location.pathname);
	const [bootError, setBootError] = useState("");

	useEffect(() => {
		api<Me & { csrf_token: string }>("/auth/me")
			.then(({ csrf_token, ...user }) => {
				setCsrf(csrf_token);
				setMe(user);
			})
			.catch((err) => {
				if (err instanceof ApiError && err.status === 401) setMe(null);
				else setBootError(err instanceof ApiError ? err.message : String(err));
			});
	}, []);

	useEffect(() => {
		const onPop = () => setPath(window.location.pathname);
		window.addEventListener("popstate", onPop);
		return () => window.removeEventListener("popstate", onPop);
	}, []);

	useEffect(() => {
		if (me === undefined) return;
		const target = me === null ? "/" : allowed(me, path) ? path : homeFor(me);
		if (target !== window.location.pathname) {
			window.history.replaceState(null, "", target);
		}
		if (target !== path) setPath(target);
	}, [me, path]);

	useEffect(() => {
		document.title =
			me && TITLES[section(path)]
				? `${TITLES[section(path)]} · LocalCBT`
				: "LocalCBT";
		document.querySelector("main")?.focus();
	}, [me, path]);

	if (bootError) {
		return (
			<main className="login">
				<p className="alert alert-error" role="alert">
					{bootError}
				</p>
				<button
					type="button"
					className="btn btn-secondary"
					onClick={() => window.location.reload()}
				>
					Coba lagi
				</button>
			</main>
		);
	}
	if (me === undefined) return <p className="muted center">Memuat…</p>;
	if (me === null) return <Login onLogin={setMe} />;

	async function logout() {
		await api("/auth/logout", { method: "POST" }).catch(() => {});
		setCsrf("");
		setMe(null);
	}

	return (
		<>
			<header className="topbar">
				<strong>LocalCBT</strong>
				<span className="topbar-user">
					<span>{me.display_name}</span>
					<button type="button" className="btn btn-ghost" onClick={logout}>
						Keluar
					</button>
				</span>
			</header>
			<main className="page" tabIndex={-1}>
				<h1>{TITLES[section(path)]}</h1>
				{section(path) === "/admin" ? (
					<Admin />
				) : section(path) === "/teacher" ? (
					<TeacherPage path={path} />
				) : (
					<p className="muted">
						Halo, {me.display_name}. Fitur halaman ini menyusul di milestone
						berikutnya.
					</p>
				)}
			</main>
		</>
	);
}

const root = document.getElementById("root");
if (root) {
	createRoot(root).render(
		<StrictMode>
			<App />
		</StrictMode>,
	);
}
