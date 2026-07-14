FROM python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS core

ARG RUST_VERSION=1.96.0
ENV PATH=/root/.cargo/bin:${PATH}

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl build-essential pkg-config \
 && rm -rf /var/lib/apt/lists/* \
 && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile minimal --default-toolchain "${RUST_VERSION}" \
 && rustup component add --toolchain "${RUST_VERSION}" rustfmt

RUN python -m pip install --no-cache-dir \
      black==26.5.1 pyright==1.1.411 \
 && cargo install --locked b3sum --version 1.8.1

COPY tools/sugar-build/entrypoint.sh /usr/local/bin/sugar-managed-entrypoint
RUN chmod 0555 /usr/local/bin/sugar-managed-entrypoint
ENTRYPOINT ["/usr/local/bin/sugar-managed-entrypoint"]
