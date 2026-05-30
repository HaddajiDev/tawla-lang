"""M16: array bounds checking."""


def test_in_bounds_access_is_fine(run_twl):
    src = "int[] a = new int[3]; a[0] = 1; a[2] = 9; print(a[2]);"
    r = run_twl(src)
    assert r.returncode == 0
    assert r.stdout == "9\n"


def test_read_out_of_bounds_aborts(run_twl):
    r = run_twl("int[] a = new int[2]; print(a[5]);")
    assert r.returncode != 0
    assert "array index out of bounds" in r.stdout


def test_negative_index_aborts(run_twl):
    r = run_twl("int[] a = new int[2]; print(a[-1]);")
    assert r.returncode != 0
    assert "array index out of bounds" in r.stdout


def test_write_out_of_bounds_aborts(run_twl):
    r = run_twl("int[] a = new int[2]; a[10] = 1;")
    assert r.returncode != 0
    assert "array index out of bounds" in r.stdout


def test_last_valid_index_ok(run_twl):
    r = run_twl("int[] a = new int[3]; a[2] = 7; print(a[2]);")
    assert r.returncode == 0
    assert r.stdout == "7\n"
