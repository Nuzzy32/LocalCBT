// Antrian jawaban di perangkat (IndexedDB) untuk gangguan jaringan. Bukan sumber kebenaran:
// yang dinilai hanya jawaban yang sudah di-ACK server. Bila IndexedDB tidak tersedia
// (mode privat / diblokir), jatuh ke memori: tetap jalan, hanya hilang saat halaman ditutup.
import type { Answer } from "./QuestionEditor";

export type QueuedAnswer = {
	key: string; // `${attemptId}:${questionId}`
	attemptId: string;
	questionId: string;
	answer: Answer | null;
	marked: boolean;
	rev: number;
};

const STORE = "answers";
const memory = new Map<string, QueuedAnswer>();
const dbReady: Promise<IDBDatabase | null> = new Promise((resolve) => {
	try {
		const req = indexedDB.open("localcbt-offline", 1);
		req.onupgradeneeded = () =>
			req.result.createObjectStore(STORE, { keyPath: "key" });
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => resolve(null);
	} catch {
		resolve(null);
	}
});

async function run<T>(
	mode: IDBTransactionMode,
	op: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T | null> {
	const db = await dbReady;
	if (!db) return null;
	return new Promise((resolve) => {
		const req = op(db.transaction(STORE, mode).objectStore(STORE));
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => resolve(null);
	});
}

export async function queuePut(entry: QueuedAnswer) {
	memory.set(entry.key, entry);
	await run("readwrite", (s) => s.put(entry));
}

export async function queueDelete(key: string) {
	memory.delete(key);
	await run("readwrite", (s) => s.delete(key));
}

export async function queueAll(): Promise<QueuedAnswer[]> {
	const stored = await run<QueuedAnswer[]>("readonly", (s) => s.getAll());
	return stored ?? [...memory.values()];
}

/** Hapus antrian attempt lain (perangkat bersama) atau attempt ini setelah selesai. */
export async function queueClear(keep?: string) {
	for (const e of await queueAll()) {
		if (e.attemptId !== keep) await queueDelete(e.key);
	}
}
