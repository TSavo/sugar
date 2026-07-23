class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


class ContextManagerContractRefV1:
    pass


class DoorB:
    pass


class With:
    def _construct_sugar(self, value: ContextManagerContractRefV1 | DoorB):
        if isinstance(value, ContextManagerContractRefV1):
            return WithResourceSugar()
        if isinstance(value, DoorB):
            return WithResourceSugar()
        raise RuntimeError
