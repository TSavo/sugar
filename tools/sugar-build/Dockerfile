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

# Mounted checkout sources precede installed packages. Third-party dependencies
# are installed exactly; Sugar's Python packages execute from /workspace/sugar.
FROM core AS python-test
ARG PYTEST_VERSION=9.1.1
ENV PYTHONPATH=/workspace/sugar/implementations/python/libsugar-py/src:/workspace/sugar/implementations/python/sugar-build-witness/src:/workspace/sugar/implementations/python/sugar-emit-python-hypothesis/src:/workspace/sugar/implementations/python/sugar-emit-python-pytest/src:/workspace/sugar/implementations/python/sugar-emit-python-unittest/src:/workspace/sugar/implementations/python/sugar-lift-py-pytest-witness/src:/workspace/sugar/implementations/python/sugar-lift-py-tests/src:/workspace/sugar/implementations/python/sugar-lift-python-source/src
RUN python -m pip install --no-cache-dir \
      pytest=="${PYTEST_VERSION}" \
      blake3==1.0.9 cbor2==6.1.3 cffi==2.1.0 hypothesis==6.156.6 \
      iniconfig==2.3.0 itsdangerous==2.2.0 packaging==26.2 pluggy==1.6.0 \
      pycparser==3.0 Pygments==2.20.0 PyNaCl==1.6.2 \
      sortedcontainers==2.4.0 typing_extensions==4.16.0 \
 && python -m pytest --version

FROM core AS solver-z3
ARG Z3_DEBIAN_VERSION=4.8.12-3.1
RUN apt-get update \
 && apt-get install -y --no-install-recommends z3="${Z3_DEBIAN_VERSION}" \
 && rm -rf /var/lib/apt/lists/* \
 && z3 --version

FROM python-test AS python-lift-closure
ARG Z3_DEBIAN_VERSION=4.8.12-3.1
ARG NUMPY_VERSION=2.5.1
ARG PANDAS_VERSION=3.0.3
RUN apt-get update \
 && apt-get install -y --no-install-recommends z3="${Z3_DEBIAN_VERSION}" \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip install --no-cache-dir \
      numpy=="${NUMPY_VERSION}" pandas=="${PANDAS_VERSION}" \
      python-dateutil==2.9.0.post0 six==1.17.0 \
      scikit-learn==1.9.0 scipy==1.18.0 joblib==1.5.3 threadpoolctl==3.6.0 narwhals==2.24.0 \
 && python -c 'import numpy, pandas; assert numpy.__version__ == "2.5.1"; assert pandas.__version__ == "3.0.3"' \
 && z3 --version

# The maximal named-task closure is deliberately cumulative. It does not rely
# on sibling stages composing: every earlier executable is inherited here.
FROM python-lift-closure AS examples-closure
ARG COQ_DEBIAN_VERSION=8.16.1+dfsg-1+b2
ARG MAVEN_DEBIAN_VERSION=3.8.7-1
ARG JAVA_VERSION=21.0.9
ARG JAVA_ARCHIVE_SHA256=810d3773df7e0d6c4394e4e244b264c8b30e0b05a0acf542d065fd78a6b65c2f
ARG NODE_VERSION=22.17.1
ARG NODE_ARCHIVE_SHA256=ff04bc7c3ed7699ceb708dbaaf3580d899ff8bf67f17114f979e83aa74fc5a49
ARG PNPM_VERSION=10.13.1
ARG VAMPIRE_VERSION=5.0.1
ARG VAMPIRE_ARCHIVE_SHA256=6ff2f42ea7fb9753ee104efc3e623d5e39443190f7c82a63e1e1517bf9d2cde3
RUN apt-get update \
 && apt-get install -y --no-install-recommends coq="${COQ_DEBIAN_VERSION}" maven="${MAVEN_DEBIAN_VERSION}" unzip \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL -o /tmp/jdk.tar.gz "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-${JAVA_VERSION}%2B10/OpenJDK21U-jdk_x64_linux_hotspot_${JAVA_VERSION}_10.tar.gz" \
 && echo "${JAVA_ARCHIVE_SHA256}  /tmp/jdk.tar.gz" | sha256sum -c - \
 && mkdir -p /opt/java \
 && tar -xzf /tmp/jdk.tar.gz -C /opt/java --strip-components=1 \
 && find /opt/java/bin -maxdepth 1 -type f -exec ln -sf {} /usr/local/bin/ \; \
 && rm /tmp/jdk.tar.gz \
 && curl -fsSL -o /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && echo "${NODE_ARCHIVE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - \
 && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
 && rm /tmp/node.tar.xz \
 && npm install --global "pnpm@${PNPM_VERSION}" \
 && curl -fsSL -o /tmp/vampire.zip \
      "https://github.com/vprover/vampire/releases/download/v${VAMPIRE_VERSION}/vampire-Linux-X64.zip" \
 && echo "${VAMPIRE_ARCHIVE_SHA256}  /tmp/vampire.zip" | sha256sum -c - \
 && python -m zipfile -e /tmp/vampire.zip /tmp/vampire \
 && install -m 0755 /tmp/vampire/vampire /usr/local/bin/vampire \
 && rm -rf /tmp/vampire /tmp/vampire.zip \
 && coqc --version \
 && PATH="/opt/java/bin:${PATH}" java --version \
 && PATH="/opt/java/bin:${PATH}" mvn --version \
 && sh -lc 'java --version && javac --version' \
 && node --version \
 && pnpm --version \
 && vampire --version
ENV JAVA_HOME=/opt/java PATH=/opt/java/bin:${PATH}
