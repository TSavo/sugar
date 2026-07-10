# GOOD TWIN: JWT-style unpadded urlsafe base64 via stdlib base64 + rstrip(b"=").
# Same real pattern as itsdangerous.encoding.base64_encode internals, without
# a third-party vendor: call CPython base64.urlsafe_b64encode then strip '='.
# Closed strip ambient (not-suffix-of("=", out)) agrees with the unpadded RHS.
import base64


def unpadded_urlsafe_b64encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def test_stdlib_base64_padding():
    assert unpadded_urlsafe_b64encode(b"provekit") == b"cHJvdmVraXQ"
