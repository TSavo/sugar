# Python end-to-end example

`double.py` and `test_double.py` are the Python production bridge fixture. The
project registers lift and pytest emit surfaces in `.sugar/config.toml`;
the CLI dispatches to those kits over RPC and keeps the shared mint/prove work.

For hermetic tests, the integration suite copies this fixture and rewrites only
manifest command paths to point at the checkout-local Python modules.
