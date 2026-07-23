class EffectBoundary: pass
class Sugar: pass
class WithResourceSugar(Sugar): pass
def create(): return EffectBoundary()
rows = {"k": create}
def write(value): return {"q8": value}
def read(message): return message["q8"]
def demand(imported):
    targetSymbol = imported
    value = rows[targetSymbol]()
    return WithResourceSugar(read(write(value)))
