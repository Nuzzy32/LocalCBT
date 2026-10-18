class ApiError(Exception):
    """Dirender sebagai ApiError API_SPEC: {"error": {code, message}, "request_id"}."""

    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        self.status, self.code, self.message, self.headers = status, code, message, headers


def not_found() -> ApiError:
    # 404 juga untuk objek yang ada tapi tidak boleh dilihat: tidak membocorkan keberadaan.
    return ApiError(404, "NOT_FOUND", "Data tidak ditemukan.")


def forbidden() -> ApiError:
    return ApiError(403, "FORBIDDEN", "Anda tidak memiliki akses.")
