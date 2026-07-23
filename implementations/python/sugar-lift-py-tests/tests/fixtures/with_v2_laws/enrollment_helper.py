def resolve(symbol):
    table = {"pytest.raises": {"kind": "contract-builder"}}
    return table.get(symbol)
