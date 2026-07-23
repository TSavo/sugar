class Sugar: pass
class WithResourceSugar(Sugar): pass
class ContextManagerContractRefV1: pass
class ContextManagerResolutionGapV1: pass
class With:
    def _construct_sugar(self, value: ContextManagerContractRefV1 | ContextManagerResolutionGapV1):
        if isinstance(value, ContextManagerContractRefV1): return WithResourceSugar()
        if isinstance(value, ContextManagerResolutionGapV1): raise RuntimeError
        raise RuntimeError
