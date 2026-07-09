def add(a, b):
    return a + b


def test_add():
    assert add(2, 3) == 5
    xs = [1, 2, 3]
    # Builtin free call: batch IR emits `call:len` + `len::builtin-universe`.
    assert len(xs) == 3
    # Method call: batch callEdges emit `method:count` (prefix must stay).
    assert xs.count(2) == 1
