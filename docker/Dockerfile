FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# ============================================================
# Base build tools and libraries (C/C++)
# ============================================================
# Compilers:
#   - gcc/g++ (apt) — default, used by most C/C++ projects
#   - clang/clang++ (apt) — alternative, repos can specify in build_steps
# Build systems: make, cmake, ninja, autotools
# Repos can override compiler via CC=/usr/bin/clang in build_steps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    clang \
    make \
    cmake \
    ninja-build \
    autoconf \
    automake \
    libtool \
    pkg-config \
    git \
    wget \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    strace \
    # Utilities needed by bomsh scripts
    xxd \
    binutils \
    elfutils \
    file \
    # curl build dependencies (mapped from config.yaml configure flags)
    # Explicit --with-* flags:
    libssl-dev \
    zlib1g-dev \
    libnghttp2-dev \
    libssh2-1-dev \
    libbrotli-dev \
    # Auto-detected by curl's ./configure (will error if partially found):
    libpsl-dev \
    libzstd-dev \
    libc-ares-dev \
    libidn2-dev \
    libpcre2-dev \
    # FFmpeg dependencies
    nasm \
    yasm \
    libx264-dev \
    libx265-dev \
    libvpx-dev \
    libopus-dev \
    libmp3lame-dev \
    libfdk-aac-dev \
    libfreetype-dev \
    libfontconfig1-dev \
    libfribidi-dev \
    libass-dev \
    # Nmap dependencies
    libpcap-dev \
    flex \
    bison \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# Python runtime dependencies for app scripts
# ============================================================
# WHY: analyze.py, compare.py, and add_repo.py all import pyyaml.
# requirements.txt is the single source of truth for Python deps,
# shared between local development (.venv) and this container.
# If a new Python dependency is added, update requirements.txt —
# do NOT add ad-hoc pip install commands here.
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# ============================================================
# Install Syft (manifest-based SBOM generation)
# ============================================================
RUN curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin

# ============================================================
# Install Go SDK (for building Go target repositories)
# ============================================================
# Go versions:
#   - 1.26.0 (official tarball) at /usr/local/go/bin/go — default
# Go 1.23+ is required by fzf and other Go targets.
# We install the official tarball to /usr/local/go.
# See .windsurf/rules/go-sdk-version.md for update policy.
# Repos needing older Go can specify GO_VERSION in build_steps.
ENV GO_VERSION=1.26.0
RUN wget -q "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -O /tmp/go.tar.gz && \
    tar -C /usr/local -xzf /tmp/go.tar.gz && \
    rm /tmp/go.tar.gz
ENV PATH="/usr/local/go/bin:/root/go/bin:${PATH}"
ENV GOPATH="/root/go"

# ============================================================
# Install Java JDK and Maven (for building Java target repos)
# ============================================================
# Java versions:
#   - OpenJDK 17 (apt) at /usr/lib/jvm/java-17-openjdk-amd64 — for most projects
#   - OpenJDK 21 (apt) at /usr/lib/jvm/java-21-openjdk-amd64 — for projects requiring JDK 21+ (e.g. checkstyle)
# Maven versions:
#   - 3.6.3 (apt) at /usr/share/maven/bin/mvn — for older projects
#   - 3.9.13 (Apache) at /opt/apache-maven-3.9.13/bin/mvn — for newer projects
# Default JAVA_HOME is JDK 21; repos can override via JAVA_HOME in build_steps
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jdk \
    openjdk-21-jdk \
    maven \
    && rm -rf /var/lib/apt/lists/*
# Default to JDK 21 for newer projects like checkstyle
ENV JAVA_HOME="/usr/lib/jvm/java-21-openjdk-amd64"
ENV MAVEN_VERSION=3.9.13
RUN wget -q "https://dlcdn.apache.org/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz" -O /tmp/maven.tar.gz && \
    tar -C /opt -xzf /tmp/maven.tar.gz && \
    rm /tmp/maven.tar.gz
# Symlink mvn3.9 for explicit version selection; default mvn uses 3.9.13
RUN ln -sf /opt/apache-maven-${MAVEN_VERSION}/bin/mvn /usr/local/bin/mvn && \
    ln -s /opt/apache-maven-${MAVEN_VERSION}/bin/mvn /usr/local/bin/mvn3.9 && \
    ln -s /usr/share/maven/bin/mvn /usr/local/bin/mvn3.6
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# ============================================================
# Install Rust toolchain (for building Rust target repos)
# ============================================================
# Rust versions:
#   - stable (rustup) — default, updated via rustup update
#   - specific versions can be installed via: rustup install 1.75.0
# rustup installs to /root/.cargo and /root/.rustup.
# We use the minimal profile (no docs/clippy/rustfmt) to
# keep the image small.  The stable toolchain is sufficient
# for all current Rust targets (e.g. oxipng ≥ 1.85.1).
# Repos needing specific Rust version can add to build_steps:
#   rustup install 1.75.0 && rustup default 1.75.0
ENV RUSTUP_HOME="/root/.rustup"
ENV CARGO_HOME="/root/.cargo"
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable --profile minimal && \
    . /root/.cargo/env && rustc --version && cargo --version
ENV PATH="/root/.cargo/bin:${PATH}"

# ============================================================
# Build bomtrace2 and bomtrace3 from omnibor/bomsh
# ============================================================
#
# IMPORTANT BUILD NOTES (read before modifying):
#
# 1. ARCHITECTURE: This image MUST be built for linux/amd64 (x86_64).
#    bomsh_hook.c includes <sys/reg.h> which only exists on x86.
#    On Apple Silicon, Docker Desktop uses QEMU emulation (slow but works).
#    The platform is enforced in docker-compose.yml.
#
# 2. STRACE VERSION PIN: The bomsh patches are fragile and only apply
#    cleanly against specific strace versions. We pin to v6.11 (verified
#    2026-02-10). If upgrading, test patches with: patch --dry-run -p1 <
#    Before changing this, verify both bomtrace2.patch and bomtrace3.patch
#    apply cleanly against the new strace tag.
#
# 3. CONFIGURE FLAGS: We use --enable-mpers=check to match the bomsh
#    project's own .devcontainer/Dockerfile. Do NOT use --disable-mpers
#    as it can cause header resolution issues on some platforms.
#
# 4. PARALLEL BUILD RACE CONDITION: bomtrace3 MUST use make -j1 (serial).
#    The bomtrace3 patch adds custom source files (bomsh_hook.c, etc.)
#    that #include "printers.h" — a file generated during the build.
#    The patched Makefile.am does not declare this dependency correctly,
#    so parallel make can compile bomsh_hook.c before printers.h exists.
#    bomtrace2 does NOT have this issue (no custom .c files added).
#
# 5. GCC STRINGOP-OVERFLOW WARNING: bomsh_hook.c has a strcpy into a
#    PATH_MAX buffer that GCC flags as a potential overflow. strace builds
#    with -Werror, so this warning becomes a fatal error. We suppress it
#    with CFLAGS+=-Wno-error=stringop-overflow. This is an upstream bomsh
#    bug, not something we introduced.
#
# 6. BUILD TIME: ~15 min native x86, ~30+ min under QEMU on Apple Silicon.
#    bomtrace2 layer is cached after first successful build.
#
# ============================================================
WORKDIR /opt
RUN git clone https://github.com/omnibor/bomsh.git

# Build bomtrace2 (parallel build OK — no custom source files)
WORKDIR /opt/bomsh-build
RUN git clone --branch v6.11 --depth 1 https://github.com/strace/strace.git strace2 && \
    cd strace2 && \
    patch -p1 < /opt/bomsh/.devcontainer/patches/bomtrace2.patch && \
    ./bootstrap && \
    ./configure --enable-mpers=check && \
    make -j$(nproc) && \
    cp src/strace /opt/bomsh/bin/bomtrace2

# Build bomtrace3 (MUST use -j1, see note 4 above)
RUN git clone --branch v6.11 --depth 1 https://github.com/strace/strace.git strace3 && \
    cd strace3 && \
    patch -p1 < /opt/bomsh/.devcontainer/patches/bomtrace3.patch && \
    cp /opt/bomsh/.devcontainer/src/*.[hc] src/ && \
    ./bootstrap && \
    ./configure --enable-mpers=check && \
    make -j1 CFLAGS="$(pkg-config --cflags 2>/dev/null) -g -O2 -Wno-error=stringop-overflow" && \
    cp src/strace /opt/bomsh/bin/bomtrace3

# Clean up build artifacts
RUN rm -rf /opt/bomsh-build

# Add bomsh bin and scripts to PATH
ENV PATH="/opt/bomsh/bin:/opt/bomsh/scripts:${PATH}"

# Copy bomsh_hook2.py to /tmp (required by bomtrace2)
RUN cp /opt/bomsh/scripts/bomsh_hook2.py /tmp/

# Patch bomsh_hook2.py: is_golang_prog() only matches /usr/lib/go-*/
# but our Go install is /usr/local/go/  —  add "local/go" path match
COPY docker/patches/bomsh_hook2_golang_path.patch /tmp/bomsh_golang.patch
RUN cd /opt/bomsh && patch -p1 < /tmp/bomsh_golang.patch && \
    cp /opt/bomsh/scripts/bomsh_hook2.py /tmp/bomsh_hook2.py && \
    rm /tmp/bomsh_golang.patch

# Go-specific bomtrace2 config (watches go compile/link tools + openat syscall)
COPY docker/bomtrace_go.conf /opt/bomsh/bin/bomtrace_go.conf

# ============================================================
# Working directory — repos are mounted here
# ============================================================
WORKDIR /workspace

CMD ["/bin/bash"]
