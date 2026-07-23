class Sugar: pass
class WithResourceSugar(Sugar): pass
class DoorB: pass
def write(value): return {"z9": value}
def read(message): return message["z9"]
class With:
    def _construct_sugar(self):
        value = read(write(DoorB()))
        if isinstance(value, DoorB): return WithResourceSugar()
        raise RuntimeError
