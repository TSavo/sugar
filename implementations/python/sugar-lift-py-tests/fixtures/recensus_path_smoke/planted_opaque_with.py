"""Unconstructed with-item plant: must residual (typed gap), never vanish."""


def run():
    with mystery():  # noqa: F821 — intentional unresolved manager
        pass
