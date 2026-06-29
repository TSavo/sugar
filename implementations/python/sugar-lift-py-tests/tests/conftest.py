# SPDX-License-Identifier: Apache-2.0
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.normpath(os.path.join(_HERE, "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
# the tests dir itself, so per-sugar tests can import the shared `factory_reduce`
# harness module.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
