from sqlalchemy.orm import as_declarative


@as_declarative()
class Base:
    pass


def A(z):
    return z


def test_a():
    assert A(5) == 5
