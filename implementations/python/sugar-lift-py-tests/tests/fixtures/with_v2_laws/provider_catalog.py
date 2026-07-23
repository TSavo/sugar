class ProtocolResource: pass
def make_payload(): return ProtocolResource()
doors = {"anything": make_payload}
def choose(target): return doors[target]()
