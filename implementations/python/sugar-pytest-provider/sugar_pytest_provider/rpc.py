import json, sys
from .declaration import PROVIDER_KIT_ID, PROVIDER_EXPORT

def kit_declaration_result():
    return {"kit": {"id": PROVIDER_KIT_ID, "language": "python", "version": "0.1.0"},
            "contractDeclarations": [],
            "providerExports": [{"bridgeSourceSymbol": PROVIDER_EXPORT,
                                 "providerKitId": PROVIDER_KIT_ID,
                                 "payload": "typed-slot:#7341"}]}

def main():
    for line in sys.stdin:
        msg=json.loads(line)
        result=kit_declaration_result() if msg.get("method")=="sugar.plugin.kit_declaration" else {"error":"unsupported"}
        print(json.dumps({"jsonrpc":"2.0","id":msg.get("id"),"result":result}),flush=True)
