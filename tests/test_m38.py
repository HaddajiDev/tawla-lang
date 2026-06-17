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


def test_sql_builtins_end_to_end(run_twl):
    src = (
        "class Main { void main() {"
        ' int db = __sql_open(":memory:");'
        ' int c = __sql_prepare(db, "CREATE TABLE t(x INT)");'
        " print(__sql_exec(c));"
        ' int ins = __sql_prepare(db, "INSERT INTO t(x) VALUES (?)");'
        " __sql_bind_int(ins, 0, 7); print(__sql_exec(ins));"
        ' int q = __sql_prepare(db, "SELECT x FROM t");'
        " int r = __sql_query(q); print(__sql_next(r)); print(__sql_col_int(r, 0));"
        " } }"
    )
    assert run_twl(src).stdout == "0\n0\n1\n7\n"
