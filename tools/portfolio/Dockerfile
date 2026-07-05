FROM ubuntu:24.04

LABEL org.opencontainers.image.title="Sugar prove portfolio"
LABEL org.opencontainers.image.description="Backend solver image for the Sugar prove portfolio"
LABEL org.opencontainers.image.authors="T Savo"

ARG CVC5_VERSION=1.2.1
ARG VAMPIRE_VERSION=v5.0.1
ARG MAUDE_VERSION=3.5.1
ARG APROVE_VERSION=master_2026_02_15
ARG CETA_VERSION=2.46
ARG CSI_VERSION=1.2.7
ARG LEAN_TOOLCHAIN=leanprover/lean4:v4.29.1
ARG MATHLIB_COMMIT=5e932f9
ARG RUST_TOOLCHAIN=stable

ENV DEBIAN_FRONTEND=noninteractive
ENV CARGO_HOME=/cache/cargo
ENV RUSTUP_HOME=/cache/rustup
ENV ELAN_HOME=/opt/elan
ENV SUGAR_LEAN_PROJECT=/opt/lean-mathlib
ENV PATH=/opt/elan/bin:/cache/cargo/bin:/usr/local/bin:/usr/bin:/bin

# Base packages include pinned solver packages from the Ubuntu 24.04 archive.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    ca-certificates \
    clang-18 \
    cmake \
    coq=8.18.0+dfsg-1build2 \
    coreutils \
    curl \
    default-jre-headless=2:1.21-75+exp1 \
    git \
    libclang-18-dev \
    libgmp10 \
    libncurses6 \
    libreadline8t64 \
    libtinfo6 \
    llvm-18-dev \
    pkg-config \
    tar \
    unzip \
    xz-utils \
    z3=4.8.12-3.1build1 \
 && ln -sf /usr/bin/llvm-config-18 /usr/local/bin/llvm-config \
 && rm -rf /var/lib/apt/lists/*

# cvc5 is installed from the static release to avoid the stale apt package.
RUN curl -fsSL \
      "https://github.com/cvc5/cvc5/releases/download/cvc5-${CVC5_VERSION}/cvc5-Linux-x86_64-static.zip" \
      -o /tmp/cvc5.zip \
 && unzip -q /tmp/cvc5.zip -d /tmp \
 && install -m 0755 /tmp/cvc5-Linux-x86_64-static/bin/cvc5 /usr/local/bin/cvc5 \
 && rm -rf /tmp/cvc5*

# Vampire is built from the pinned upstream release tag.
RUN git clone --depth 1 --branch "${VAMPIRE_VERSION}" https://github.com/vprover/vampire.git /opt/vampire \
 && cd /opt/vampire \
 && cmake -DCMAKE_BUILD_TYPE=Release . \
 && make -j"$(nproc)" \
 && ln -sf /opt/vampire/vampire /usr/local/bin/vampire

# Maude needs its release prelude beside the binary, so expose it through a wrapper.
# The Maude 3.5.1 linux-x86_64 release zip ships the binary as `maude` at the
# archive root, alongside the *.maude prelude files.
RUN install -d "/opt/maude-${MAUDE_VERSION}" \
 && curl -fsSL \
      "https://github.com/maude-lang/Maude/releases/download/Maude${MAUDE_VERSION}/Maude-${MAUDE_VERSION}-linux-x86_64.zip" \
      -o "/tmp/maude-${MAUDE_VERSION}-linux-x86_64.zip" \
 && unzip -q "/tmp/maude-${MAUDE_VERSION}-linux-x86_64.zip" -d "/opt/maude-${MAUDE_VERSION}" \
 && chmod +x "/opt/maude-${MAUDE_VERSION}/maude" \
 && printf '%s\n' \
      '#!/usr/bin/env bash' \
      'set -e' \
      'export MAUDE_LIB="${MAUDE_LIB:-/opt/maude-3.5.1}"' \
      'exec /opt/maude-3.5.1/maude "$@"' \
      > /usr/local/bin/maude \
 && chmod +x /usr/local/bin/maude \
 && rm -f "/tmp/maude-${MAUDE_VERSION}-linux-x86_64.zip"

# AProVE is used by the CeTA gate as the termination certificate producer.
RUN install -d "/opt/aprove-${APROVE_VERSION}" \
 && curl -fsSL \
      "https://github.com/aprove-developers/aprove-releases/releases/download/${APROVE_VERSION}/aprove.jar" \
      -o "/opt/aprove-${APROVE_VERSION}/aprove.jar" \
 && ln -sfn "/opt/aprove-${APROVE_VERSION}" /opt/aprove \
 && printf '%s\n' \
      '#!/usr/bin/env sh' \
      'exec java -jar /opt/aprove/aprove.jar "$@"' \
      > /usr/local/bin/aprove \
 && chmod +x /usr/local/bin/aprove

# CeTA verifies CPF certificates emitted by AProVE and CSI.
# Best effort: the uibk download URL has been unstable. If the fetch fails the
# build still succeeds, and the Maude reduce-verdict gate runs in untrusted mode
# (the portfolio falls through to vampire/coq for those obligations, per the
# equational-portfolio-extension spec). To enable the gate, install `ceta` and
# `csi` onto PATH separately. See tools/portfolio/maude-ceta-install.md.
RUN { install -d "/opt/ceta-${CETA_VERSION}" \
   && curl -fsSL \
        "https://cl-informatik.uibk.ac.at/software/ceta/downloads/ceta-${CETA_VERSION}-linux-x86_64.tar.gz" \
        -o "/tmp/ceta-${CETA_VERSION}-linux-x86_64.tar.gz" \
   && tar -xzf "/tmp/ceta-${CETA_VERSION}-linux-x86_64.tar.gz" -C "/opt/ceta-${CETA_VERSION}" --strip-components=1 \
   && ln -sf "/opt/ceta-${CETA_VERSION}/ceta" /usr/local/bin/ceta \
   && rm -f "/tmp/ceta-${CETA_VERSION}-linux-x86_64.tar.gz" ; } \
 || echo "WARNING: CeTA install skipped (download URL unavailable); the Maude/CeTA gate runs in untrusted mode"

# CSI provides the confluence checker used by the Maude CeTA gate (best effort, see above).
RUN { install -d "/opt/csi-${CSI_VERSION}" \
   && curl -fsSL \
        "https://cl-informatik.uibk.ac.at/software/csi/downloads/csi-${CSI_VERSION}-linux-x86_64.tar.gz" \
        -o "/tmp/csi-${CSI_VERSION}-linux-x86_64.tar.gz" \
   && tar -xzf "/tmp/csi-${CSI_VERSION}-linux-x86_64.tar.gz" -C "/opt/csi-${CSI_VERSION}" --strip-components=1 \
   && ln -sf "/opt/csi-${CSI_VERSION}/csi" /usr/local/bin/csi \
   && rm -f "/tmp/csi-${CSI_VERSION}-linux-x86_64.tar.gz" ; } \
 || echo "WARNING: CSI install skipped (download URL unavailable); the Maude/CeTA gate runs in untrusted mode"

# Rust is included so the image can build and run verifier and compiler crates.
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --default-toolchain "${RUST_TOOLCHAIN}" --profile minimal --no-modify-path \
 && rustc --version \
 && cargo --version

# Lean uses elan plus a pinned mathlib cache fetched through Lake.
RUN curl https://elan.lean-lang.org/elan-init.sh -sSf \
      | sh -s -- -y --default-toolchain "${LEAN_TOOLCHAIN}" --no-modify-path \
 && lean --version \
 && lake --version \
 && install -d /opt/lean-mathlib/SugarMathlib \
 && printf '%s\n' "${LEAN_TOOLCHAIN}" > /opt/lean-mathlib/lean-toolchain \
 && printf '%s\n' \
      'import Lake' \
      'open Lake DSL' \
      '' \
      'package sugar_mathlib' \
      '' \
      'require mathlib from git' \
      "  \"https://github.com/leanprover-community/mathlib4.git\" @ \"${MATHLIB_COMMIT}\"" \
      '' \
      'lean_lib SugarMathlib' \
      > /opt/lean-mathlib/lakefile.lean \
 && printf '%s\n' 'import Mathlib' > /opt/lean-mathlib/SugarMathlib.lean \
 && cd /opt/lean-mathlib \
 && lake update \
 && lake exe cache get \
 && printf '%s\n' \
      '#!/usr/bin/env bash' \
      'set -euo pipefail' \
      'cd /opt/lean-mathlib' \
      'exec lake env lean "$@"' \
      > /usr/local/bin/sugar-lean-solve \
 && chmod +x /usr/local/bin/sugar-lean-solve

COPY verify-portfolio.sh /opt/portfolio/verify-portfolio.sh
RUN chmod +x /opt/portfolio/verify-portfolio.sh

RUN chown -R 1000:1000 /opt /cache /workspace
USER 1000

WORKDIR /workspace
CMD ["bash"]
