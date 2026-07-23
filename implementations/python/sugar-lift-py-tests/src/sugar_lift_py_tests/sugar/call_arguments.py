"""Role-aware projection of already-constructed call arguments."""


def positional_term(value, *, owner: str):
    from sugar_lift_py_tests.floor.spread_value import SpreadValue

    if type(value) is SpreadValue:
        return value.call_term(owner=owner)
    return value.to_term(owner=owner)


def keyword_term(name, value, *, owner: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    if name is None:
        return ctor("python:double_starred_kwarg", [value.to_term(owner=owner)])
    return ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
