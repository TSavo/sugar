class EffectBoundary:
    pass


def create():
    return EffectBoundary()


rows = {"x": create}


def unused(symbol):
    builder = rows.get(symbol)
    return builder()
