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

# Capability stages are additive. Their ARG defaults mirror sugar-build.toml;
# publishing automation must build these exact defaults and record RepoDigests.
FROM core AS solver-z3
ARG Z3_DEBIAN_VERSION=4.8.12-3.1
RUN apt-get update \
 && apt-get install -y --no-install-recommends z3="${Z3_DEBIAN_VERSION}" \
 && rm -rf /var/lib/apt/lists/* \
 && z3 --version

FROM core AS solver-coq
ARG COQ_VERSION=8.18.0
# Coq's existing portfolio owner is Ubuntu 24.04's exact 8.18.0 package. Keep
# this stage explicit until its Debian-compatible immutable closure is built.
RUN test "${COQ_VERSION}" = "8.18.0"

FROM core AS python-scientific
ARG NUMPY_VERSION=2.5.1
ARG PANDAS_VERSION=3.0.3
RUN python -m pip install --no-cache-dir \
      numpy=="${NUMPY_VERSION}" pandas=="${PANDAS_VERSION}" \
 && python -c 'import numpy, pandas; print(numpy.__version__, pandas.__version__)'

FROM core AS java
ARG JAVA_VERSION=21
ARG MAVEN_VERSION=3.8.7
# Versions are first-class even though this closure still needs its immutable
# Debian package revision adjudicated before publication.
RUN test "${JAVA_VERSION}" = 21 && test "${MAVEN_VERSION}" = 3.8.7

FROM core AS node
ARG NODE_VERSION=22.17.1
ARG PNPM_VERSION=10.13.1
RUN curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && tar -xJf "node-v${NODE_VERSION}-linux-x64.tar.xz" -C /usr/local --strip-components=1 \
 && rm "node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && npm install --global "pnpm@${PNPM_VERSION}" \
 && node --version \
 && pnpm --version

FROM core AS vampire
ARG VAMPIRE_VERSION=5.0.1
RUN curl -fsSL -o /tmp/vampire.zip \
      "https://github.com/vprover/vampire/releases/download/v${VAMPIRE_VERSION}/vampire-Linux-X64.zip" \
 && python -m zipfile -e /tmp/vampire.zip /tmp/vampire \
 && install -m 0755 /tmp/vampire/vampire /usr/local/bin/vampire \
 && rm -rf /tmp/vampire /tmp/vampire.zip \
 && vampire --version
