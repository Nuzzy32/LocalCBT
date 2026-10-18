from control_center import describe


def test_describe() -> None:
    assert describe(200, b'{"database_status":"OK"}') == ("● RUNNING", "● OK")
    assert describe(503, b'{"database_status":"DOWN"}') == ("● RUNNING", "● DOWN")
    assert describe(None, b"")[0].startswith("● STOPPED")
    assert describe(0, b"")[0].startswith("● STOPPED")
    # Body aneh tidak boleh jadi hijau
    assert describe(200, b"not json")[1] == "● DOWN"
    assert describe(500, b"")[0] == "● ERROR (HTTP 500)"
