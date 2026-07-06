"""Small real slice of itsdangerous (url_safe.py base64 helpers), used as the
Criterion 14 conservation ratchet's small in-scope vendor fixture. Kept
verbatim-shaped (not paraphrased) so the line count/content is a faithful
stand-in for the real module.
"""

import base64


def base64_encode(string):
    """Base64 encode a string of bytes or text.

    The resulting bytestring is safe for putting in URLs.
    """
    if isinstance(string, str):
        string = string.encode("utf-8")
    return base64.urlsafe_b64encode(string).rstrip(b"=")


def base64_decode(string):
    """Base64 decode a URL-safe string.

    :param string: The string to decode.
    """
    if isinstance(string, str):
        string = string.encode("ascii")
    string += b"=" * (-len(string) % 4)
    try:
        return base64.urlsafe_b64decode(string)
    except (TypeError, ValueError) as e:
        raise Exception("Invalid base64-encoded data") from e
