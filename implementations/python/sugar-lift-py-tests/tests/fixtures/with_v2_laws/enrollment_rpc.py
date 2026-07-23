class EffectBoundary: pass
class Sugar: pass
class WithResourceSugar(Sugar): pass
def create(): return EffectBoundary()
rows = {"k": create}
def write_spelling(value): return {"q7": value}
def read_spelling(message): return message["q7"]
def demand(imported):
    targetSymbol = imported
    key = read_spelling(write_spelling(targetSymbol))
    value = rows[key]()
    return WithResourceSugar(value)
