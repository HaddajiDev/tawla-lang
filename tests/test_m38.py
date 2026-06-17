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


def _main(body):
    return 'import "Sql.twl"; class Main { void main() { ' + body + " } }"


def test_sql_insert_and_query(run_twl):
    body = (
        'Db db = new Db(":memory:");'
        ' db.exec("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, age INT)");'
        ' Stmt ins = db.prepare("INSERT INTO users(name, age) VALUES (?, ?)");'
        ' ins.bindString(0, "Ada"); ins.bindInt(1, 36); ins.exec();'
        ' Stmt q = db.prepare("SELECT id, name, age FROM users WHERE age > ?");'
        " q.bindInt(0, 18); Rows r = q.query();"
        ' while (r.next()) { print(r.getString("name")); print(r.getIntAt(2)); }'
    )
    assert run_twl(_main(body)).stdout == "Ada\n36\n"


def test_sql_multiple_rows(run_twl):
    body = (
        'Db db = new Db(":memory:"); db.exec("CREATE TABLE t(x INT)");'
        ' Stmt ins = db.prepare("INSERT INTO t(x) VALUES (?)");'
        " ins.bindInt(0, 1); ins.exec();"
        ' Stmt ins2 = db.prepare("INSERT INTO t(x) VALUES (?)");'
        " ins2.bindInt(0, 2); ins2.exec();"
        ' Rows r = db.prepare("SELECT x FROM t ORDER BY x").query();'
        ' int sum = 0; while (r.next()) { sum = sum + r.getInt("x"); } print(sum);'
    )
    assert run_twl(_main(body)).stdout == "3\n"


def test_sql_float_roundtrip(run_twl):
    body = (
        'Db db = new Db(":memory:"); db.exec("CREATE TABLE m(v REAL)");'
        ' Stmt ins = db.prepare("INSERT INTO m(v) VALUES (?)");'
        " ins.bindFloat(0, 2.5); ins.exec();"
        ' Rows r = db.prepare("SELECT v FROM m").query();'
        ' r.next(); print(r.getFloat("v"));'
    )
    assert run_twl(_main(body)).stdout == "2.5\n"


def test_sql_null_handling(run_twl):
    body = (
        'Db db = new Db(":memory:"); db.exec("CREATE TABLE t(name TEXT)");'
        ' db.exec("INSERT INTO t(name) VALUES (NULL)");'
        ' Rows r = db.prepare("SELECT name FROM t").query(); r.next();'
        ' if (r.isNull("name")) { print("null"); } else { print(r.getString("name")); }'
    )
    assert run_twl(_main(body)).stdout == "null\n"


def test_sql_error_is_catchable(run_twl):
    body = (
        'Db db = new Db(":memory:");'
        ' fuck_around { db.exec("NOT VALID SQL"); print("ran"); }'
        ' find_out (e) { print("caught"); }'
    )
    assert run_twl(_main(body)).stdout == "caught\n"


def test_sql_uncaught_error_exits_nonzero(run_twl):
    body = 'Db db = new Db(":memory:"); db.exec("NOT VALID SQL");'
    r = run_twl(_main(body))
    assert r.returncode != 0
