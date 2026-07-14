FROM python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS core

ARG RUST_VERSION=1.96.0
ARG PYRIGHT_NODE_VERSION=26.5.0
ENV PATH=/root/.cargo/bin:${PATH} \
    PYRIGHT_PYTHON_ENV_DIR=/opt/pyright/nodeenv \
    PYRIGHT_PYTHON_GLOBAL_NODE=0

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl build-essential pkg-config \
 && rm -rf /var/lib/apt/lists/* \
 && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile minimal --default-toolchain "${RUST_VERSION}" \
 && rustup component add --toolchain "${RUST_VERSION}" rustfmt

# Force pyright-python to select and retain its private Node runtime while the
# build has network access. This is Pyright's implementation detail, not the
# separately declared node capability.
RUN python -m pip install --no-cache-dir \
      black==26.5.1 pyright==1.1.411 \
 && cargo install --locked b3sum --version 1.8.1 \
 && PYRIGHT_PYTHON_NODE_VERSION="${PYRIGHT_NODE_VERSION}" python -m pyright --version \
 && mkdir -p /opt/pyright \
 && python -c 'from pyright.node import version; print("node " + ".".join(map(str, version("node"))))' \
      > /opt/pyright/node-version \
 && test -x /opt/pyright/nodeenv/bin/node

COPY tools/sugar-build/entrypoint.sh /usr/local/bin/sugar-managed-entrypoint
RUN chmod 0555 /usr/local/bin/sugar-managed-entrypoint
ENTRYPOINT ["/usr/local/bin/sugar-managed-entrypoint"]
