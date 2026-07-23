class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


class DoorB:
    pass


doors = {"arbitrary": DoorB()}


def require(key):
    return doors.get(key)


class With:
    def _construct_sugar(self):
        value = require("arbitrary")
        if isinstance(value, DoorB):
            return WithResourceSugar()
        raise RuntimeError
