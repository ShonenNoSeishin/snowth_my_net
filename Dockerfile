# syntax=docker/dockerfile:1.7
# snowth_my_net image: python:3.13-slim, non-root, read-only friendly, supercronic scheduler.
ARG PYTHON_VERSION=3.13
ARG SUPERCRONIC_VERSION=v0.2.49

# --------------------------------------------------------------------------- build
FROM python:${PYTHON_VERSION}-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-compile .

# --------------------------------------------------------------------------- supercronic
# Static binaries, checked against the SHA-256 published with the release.
FROM scratch AS supercronic-amd64
ARG SUPERCRONIC_VERSION
ADD --checksum=sha256:a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1 --chmod=0755 \
    https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64 /supercronic

FROM scratch AS supercronic-arm64
ARG SUPERCRONIC_VERSION
ADD --checksum=sha256:02aa0cb229ba09050cba6638059dadb9eedc2276632ea43d6a57a2f8c1629dd5 --chmod=0755 \
    https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-arm64 /supercronic

ARG TARGETARCH
FROM supercronic-${TARGETARCH} AS supercronic

# --------------------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim AS runtime
LABEL org.opencontainers.image.title="snowth_my_net" \
      org.opencontainers.image.description="Lightweight read-only SNMP network mapper" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp \
    SNOWTH_CONFIG=/etc/snowth_my_net/config.yml \
    SNOWTH_STATE_DIR=/var/lib/snowth_my_net \
    SNOWTH_OUTPUT_DIR=/output \
    SNOWTH_SECRETS_DIR=/run/secrets \
    SNOWTH_EXTENSIONS_DIR=/etc/snowth_my_net/extensions
COPY --from=build /opt/venv /opt/venv
COPY --from=supercronic /supercronic /usr/local/bin/supercronic
COPY docker/entrypoint.sh /usr/local/bin/snowth-entrypoint
RUN /opt/venv/bin/python -m pip uninstall -y pip \
 && rm -rf /usr/local/lib/python3*/site-packages/pip /usr/local/lib/python3*/site-packages/pip-* \
      /usr/local/bin/pip /usr/local/bin/pip3* \
 && /opt/venv/bin/python -m compileall -q /opt/venv/lib \
 && groupadd --system --gid 10001 snowth \
 && useradd --system --uid 10001 --gid snowth --home-dir /var/lib/snowth_my_net \
      --shell /usr/sbin/nologin snowth \
 && mkdir -p /var/lib/snowth_my_net /output /etc/snowth_my_net/extensions \
 && chown snowth:snowth /var/lib/snowth_my_net /output \
 && chmod 0755 /usr/local/bin/snowth-entrypoint
USER 10001:10001
WORKDIR /var/lib/snowth_my_net
HEALTHCHECK --interval=5m --timeout=30s --start-period=30m --retries=2 \
    CMD ["snowth_my_net", "-q", "health"]
ENTRYPOINT ["/usr/local/bin/snowth-entrypoint"]
CMD ["scheduler"]

# --------------------------------------------------------------------------- tests
# docker compose --profile test run --rm tests
FROM build AS test
RUN /opt/venv/bin/pip install ".[test]" \
 && groupadd --system --gid 10001 snowth \
 && useradd --system --uid 10001 --gid snowth --home-dir /tmp --shell /usr/sbin/nologin snowth
COPY tests ./tests
COPY examples ./examples
COPY tools ./tools
ENV PATH=/opt/venv/bin:$PATH HOME=/tmp PYTHONDONTWRITEBYTECODE=1
# /certs: shared with the fake push server; a named volume inherits this ownership.
RUN mkdir -p /certs && chown -R snowth:snowth /src /certs
USER 10001:10001
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
