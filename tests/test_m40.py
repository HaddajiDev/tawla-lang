"""M40: API ergonomics — string interpolation + toJson()."""


def test_tostring_universal(run_twl):
    src = (
        "class Main { void main() {"
        ' print(toString("x")); print(toString(true)); print(toString(false));'
        " print(toString(42)); print(toString(1.5)); } }"
    )
    assert run_twl(src).stdout == "x\ntrue\nfalse\n42\n1.5\n"


def test_interp_basic(run_twl):
    src = (
        "class Main { void main() {"
        ' string n = "Ada"; int x = 3;'
        ' print("hi ${n}, ${x + 1} items");'
        ' print("${true}|${1.5}|$5.00"); } }'
    )
    assert run_twl(src).stdout == "hi Ada, 4 items\ntrue|1.5|$5.00\n"


def test_interp_plain_and_escapes(run_twl):
    src = 'class Main { void main() { print("a\\tb"); print("no interp here"); } }'
    assert run_twl(src).stdout == "a\tb\nno interp here\n"


def test_json_escape(run_twl):
    src = (
        "class Main { void main() {"
        ' print(__json_escape("hi"));'
        " string z; print(__json_escape(z)); } }"   # null -> null
    )
    assert run_twl(src).stdout == '"hi"\nnull\n'


def _prog(body, classes=""):
    return classes + " class Main { void main() { " + body + " } }"


def test_tojson_flat(run_twl):
    classes = (
        "class User {"
        " public int id; public string name; public bool active;"
        " public User(int id, string name, bool active) {"
        "   this.id = id; this.name = name; this.active = active; } }"
    )
    body = 'User u = new User(1, "Ada", true); print(u.toJson());'
    assert run_twl(_prog(body, classes)).stdout == '{"id":1,"name":"Ada","active":true}\n'


def test_tojson_string_escaping_and_null(run_twl):
    classes = (
        "class Box { public string a; public string b;"
        " public Box(string a) { this.a = a; } }"
    )
    body = 'Box x = new Box("he\\"llo"); print(x.toJson());'
    assert run_twl(_prog(body, classes)).stdout == '{"a":"he\\"llo","b":null}\n'


def test_tojson_nested_object(run_twl):
    classes = (
        "class Addr { public string city; public Addr(string c) { this.city = c; } }"
        " class Person { public string name; public Addr addr;"
        "   public Person(string n, Addr a) { this.name = n; this.addr = a; } }"
    )
    body = 'Person p = new Person("Ada", new Addr("NYC")); print(p.toJson());'
    assert run_twl(_prog(body, classes)).stdout == '{"name":"Ada","addr":{"city":"NYC"}}\n'


def test_tojson_array(run_twl):
    classes = (
        "class Bag { public int[] xs;"
        " public Bag() { this.xs = new int[3]; this.xs[0]=1; this.xs[1]=2; this.xs[2]=3; } }"
    )
    body = "Bag b = new Bag(); print(b.toJson());"
    assert run_twl(_prog(body, classes)).stdout == '{"xs":[1,2,3]}\n'


def test_tojson_user_defined_wins(run_twl):
    classes = (
        'class C { public int n; public C() { this.n = 5; }'
        ' public string toJson() { return "custom"; } }'
    )
    body = "C c = new C(); print(c.toJson());"
    assert run_twl(_prog(body, classes)).stdout == "custom\n"
