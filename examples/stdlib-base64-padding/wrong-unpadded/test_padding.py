# OUT OF SCOPE for the logo ambient (closed not-suffix-of("=", out)).
#
# Correct unpadded value: b"cHJvdmVraXQ"
# This flips the last byte to b"cHJvdmVraXR" -- still unpadded (no trailing '=').
# Closed strip ambient does NOT refute a wrong-but-unpadded RHS; the logo claim
# is specifically "no padding" / no trailing '=', not full base64 injectivity.
#
# Receipt: prove consistency stays discharged (intentionally). If a future open
# dig ambient ever unsat-es this, update the logo claim + run-logo-receipt.sh.
import base64


def unpadded_urlsafe_b64encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def test_stdlib_base64_padding():
    assert unpadded_urlsafe_b64encode(b"provekit") == b"cHJvdmVraXR"
