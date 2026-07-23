from enrollment_helper import resolve


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def demand(imported):
    targetSymbol = imported
    return WithResourceSugar(resolve(targetSymbol))
