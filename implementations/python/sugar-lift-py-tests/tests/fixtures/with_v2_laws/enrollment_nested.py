class EffectBoundary:
    pass


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def construct():
    return EffectBoundary()


doors = {"k": construct}


def first(symbol):
    return second(symbol)


def second(symbol):
    return doors.get(symbol)()


def demand(imported):
    targetSymbol = imported
    return WithResourceSugar(first(targetSymbol))
