class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def demand(imported, module, runtime_name):
    targetSymbol = imported
    registry = getattr(module, runtime_name)
    return WithResourceSugar(registry[targetSymbol])
