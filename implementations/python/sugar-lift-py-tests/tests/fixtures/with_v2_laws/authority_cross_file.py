from authority_helper import DoorB, build_authority
class Sugar: pass
class WithResourceSugar(Sugar): pass
class With:
    def _construct_sugar(self):
        value = build_authority()
        if isinstance(value, DoorB): return WithResourceSugar()
        raise RuntimeError
