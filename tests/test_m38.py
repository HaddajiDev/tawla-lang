"""M38: SQLite persistence (Sql.twl)."""


def test_sqlite_runtime_roundtrip():
    from tawla.sqlite_runtime import STATE
    STATE.reset()
    db = STATE.open(":memory:")
    assert db >= 0
    s = STATE.prepare(db, "CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, age INT)")
    assert STATE.exec(s) == 0
    ins = STATE.prepare(db, "INSERT INTO users(name, age) VALUES (?, ?)")
    STATE.bind_str(ins, 0, "Ada")
    STATE.bind_int(ins, 1, 36)
    assert STATE.exec(ins) == 0
    q = STATE.prepare(db, "SELECT id, name, age FROM users WHERE age > ?")
    STATE.bind_int(q, 0, 18)
    r = STATE.query(q)
    assert r >= 0
    assert STATE.next(r) == 1
    assert STATE.col_index(r, "name") == 1
    assert STATE.col_str(r, 1) == "Ada"
    assert STATE.col_int(r, 2) == 36
    assert STATE.is_null(r, 1) == 0
    assert STATE.next(r) == 0
    # error path: bad SQL -> status 1, message stashed
    bad = STATE.prepare(db, "NOT VALID SQL")
    assert STATE.exec(bad) == 1
    assert STATE.error() != ""
    STATE.reset()
