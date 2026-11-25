# The sandbox image, layered by tier. Build it with `kt-sandbox build`.
#
# `slim` is always installed; EXTRAS adds the tiers named in apt/ and pip/.
# The tiers and their notes/ are kept in /usr/local/share/kt-sandbox for
# kt-sandbox-about.
# The builder copies the installed kt_sandbox package into kt_sandbox/; it runs
# from /opt/kt-sandbox with only the packages in the runtime-requirements files.
# Each command is a Python script, so its name shows in the process list.
ARG BASE=python:3.12-slim
FROM ${BASE}

ARG EXTRAS=""
ARG EXTRA_APT=""
ARG EXTRA_PIP=""

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg

COPY apt /tmp/tiers/apt
COPY pip /tmp/tiers/pip

RUN set -eu; \
    packages="$(for tier in slim $(echo "$EXTRAS" | tr ',' ' '); do cat "/tmp/tiers/apt/$tier.txt" 2>/dev/null || true; done) $EXTRA_APT"; \
    apt-get update; \
    apt-get install -y --no-install-recommends $packages; \
    rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    for tier in slim $(echo "$EXTRAS" | tr ',' ' '); do \
        if grep -qv '^#' "/tmp/tiers/pip/$tier.txt" 2>/dev/null; then pip install -r "/tmp/tiers/pip/$tier.txt"; fi; \
    done; \
    if [ -n "$EXTRA_PIP" ]; then pip install $EXTRA_PIP; fi

RUN useradd --create-home --shell /bin/bash --uid 1000 sandbox \
    && echo 'sandbox ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/sandbox \
    && chmod 0440 /etc/sudoers.d/sandbox \
    && mkdir -p /work \
    && chown sandbox:sandbox /work

# KohakuTerrarium's web frontend (web_dist) is never served from a sandbox.
COPY runtime-requirements.txt runtime-requirements-no-deps.txt /tmp/
RUN set -eu; \
    pip install -r /tmp/runtime-requirements.txt; \
    pip install --no-deps -r /tmp/runtime-requirements-no-deps.txt; \
    rm -rf "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/kohakuterrarium/web_dist"; \
    rm -rf /tmp/runtime-requirements.txt /tmp/runtime-requirements-no-deps.txt /tmp/tiers

COPY notes /tmp/notes
RUN set -eu; \
    mkdir -p /usr/local/share/kt-sandbox/notes; \
    for tier in slim $(echo "$EXTRAS" | tr ',' ' '); do \
        echo "$tier" >> /usr/local/share/kt-sandbox/tiers; \
        if [ -f "/tmp/notes/$tier.md" ]; then cp "/tmp/notes/$tier.md" /usr/local/share/kt-sandbox/notes/; fi; \
    done; \
    chmod -R u=rwX,go=rX /usr/local/share/kt-sandbox; \
    rm -rf /tmp/notes

COPY kt_sandbox /opt/kt-sandbox/kt_sandbox
ENV PYTHONPATH=/opt/kt-sandbox
RUN set -eu; \
    python -m compileall -q /opt/kt-sandbox; \
    wrap() { printf '#!/usr/bin/env python\nimport runpy, sys\nsys.path.insert(0, "/opt/kt-sandbox")\nrunpy.run_module("%s", run_name="__main__", alter_sys=True)\n' "$1" > "/usr/local/bin/$2"; }; \
    wrap kt_sandbox.server kt-sandbox-mcp; \
    wrap kt_sandbox.server.about kt-sandbox-about; \
    wrap kt_sandbox kt-sandbox; \
    wrap kt_sandbox.server.files kt-sandbox-file; \
    chmod 0755 /usr/local/bin/kt-sandbox-mcp /usr/local/bin/kt-sandbox-about /usr/local/bin/kt-sandbox /usr/local/bin/kt-sandbox-file

USER sandbox
WORKDIR /work
CMD ["sleep", "infinity"]
