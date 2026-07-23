class Sugar: pass
class WithResourceSugar(Sugar): pass
class DoorB: pass
def make_authority(): return DoorB()
def outer(): return make_authority()
class With:
    def _construct_sugar(self):
        value = outer()
        if isinstance(value, DoorB): return WithResourceSugar()
        raise RuntimeError
