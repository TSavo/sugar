from provider_catalog import choose as q


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def demand(imported):
    targetSymbol = imported
    return WithResourceSugar(q(targetSymbol))
