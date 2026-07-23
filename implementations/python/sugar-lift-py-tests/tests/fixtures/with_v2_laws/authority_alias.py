from provider_authority import DoorB as Q


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


class ContextManagerContractRefV1:
    pass


class With:
    def _construct_sugar(self, value: ContextManagerContractRefV1 | Q):
        if isinstance(value, Q):
            return WithResourceSugar()
        raise RuntimeError
