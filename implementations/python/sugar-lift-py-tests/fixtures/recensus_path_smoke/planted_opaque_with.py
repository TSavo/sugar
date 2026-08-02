"""Unconstructed with-item plant: must remain accounted, never vanish."""


def run():
    with mystery():  # noqa: F821 — intentional unresolved manager
        pass
