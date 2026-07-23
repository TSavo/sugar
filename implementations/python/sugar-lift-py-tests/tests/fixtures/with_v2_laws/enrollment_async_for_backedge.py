class Boundary:
    pass


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def build():
    return Boundary()


table = {"anything": build}


async def demand(lookup_key, xs, ready):
    chosen = table[lookup_key]
    async for item in xs:
        if ready:
            return WithResourceSugar(carried)
        carried = chosen()
