class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


class With:
    def _construct_sugar(self, module, runtime_name):
        value = getattr(module, runtime_name)()
        return WithResourceSugar(value)
