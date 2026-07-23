class ProtocolResource:
    pass


def create():
    return ProtocolResource()


rows = {"k": create}


def resolve(symbol):
    return rows.get(symbol)()
