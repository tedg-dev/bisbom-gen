FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# ============================================================
# Base build tools and libraries
# ============================================================
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

# ============================================================
# Working directory — repos are mounted here
# ============================================================
WORKDIR /workspace

CMD ["/bin/bash"]
