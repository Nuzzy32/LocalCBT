export type Role = "ADMIN" | "TEACHER" | "PROCTOR" | "STUDENT";
export type Me = {
	id: string;
	username: string;
	display_name: string;
	roles: Role[];
};

export class ApiError extends Error {
	constructor(
		readonly status: number,
		readonly code: string,
		message: string,
	) {
		super(message);
	}
}

export const EXPIRED_FLAG = "localcbt.sessionExpired";
let csrfToken = "";

export function setCsrf(token: string) {
	csrfToken = token;
}

export async function api<T>(
	path: string,
	init: { method?: string; json?: unknown; form?: FormData } = {},
): Promise<T> {
	const headers: Record<string, string> = { "X-CSRF-Token": csrfToken };
	let body: BodyInit | undefined;
	if (init.json !== undefined) {
		headers["Content-Type"] = "application/json";
		body = JSON.stringify(init.json);
	} else if (init.form) {
		body = init.form;
	}
	let res: Response;
	try {
		res = await fetch(`/api/v1${path}`, {
			method: init.method ?? (body ? "POST" : "GET"),
			headers,
			body,
			credentials: "same-origin",
		});
	} catch {
		throw new ApiError(
			0,
			"NETWORK_UNAVAILABLE",
			"Koneksi ke server terputus. Periksa jaringan.",
		);
	}
	if (res.status === 204) return undefined as T;
	const data = await res.json().catch(() => null);
	if (!res.ok) {
		const err = data?.error ?? {};
		if (err.code === "SESSION_EXPIRED" && path !== "/auth/me") {
			try {
				sessionStorage.setItem(EXPIRED_FLAG, "1");
			} catch {}
			window.location.assign("/");
		}
		throw new ApiError(
			res.status,
			err.code ?? "UNKNOWN",
			err.message ?? "Terjadi kesalahan. Coba lagi.",
		);
	}
	return data as T;
}

export const ROLE_HOME: [Role, string][] = [
	["ADMIN", "/admin"],
	["TEACHER", "/teacher"],
	["PROCTOR", "/proctor"],
	["STUDENT", "/student"],
];
