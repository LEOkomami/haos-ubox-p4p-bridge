FROM ghcr.io/home-assistant/base:3.22@sha256:0eda502b4d16e0433ace512d857ec3e86497d4214091ee459078ee4df6373f63

ARG BUILD_VERSION=0.1.3
ARG BUILD_ARCH=aarch64
ARG UBOX_REVISION=6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8
ARG MEDIAMTX_VERSION=1.21.0
ARG MEDIAMTX_SHA256=a8113b5928ba1a934b81557b61b8a07954b76921a4b567d54c7f086f8b39d9a2

LABEL io.hass.type="app" io.hass.version="${BUILD_VERSION}" io.hass.arch="aarch64"
ENV PATH="/opt/venv/bin:${PATH}" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt /tmp/requirements.txt
RUN test "${BUILD_ARCH}" = aarch64 \
    && test "$(uname -m)" = aarch64 \
    && apk add --no-cache python3 py3-pip ffmpeg libstdc++ ca-certificates \
    && apk add --no-cache --virtual .build-deps build-base python3-dev curl git \
    && python3 -m venv /opt/venv \
    && pip install --no-cache-dir --no-binary=kcp --require-hashes -r /tmp/requirements.txt \
    && git init /opt/ubox-p4p \
    && git -C /opt/ubox-p4p remote add origin https://github.com/mahumadad/ubox-p4p.git \
    && git -C /opt/ubox-p4p fetch --depth 1 origin "${UBOX_REVISION}" \
    && git -C /opt/ubox-p4p checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/ubox-p4p rev-parse HEAD)" = "${UBOX_REVISION}" \
    && rm -rf /opt/ubox-p4p/.git \
    && curl -fL --retry 3 "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_linux_arm64.tar.gz" -o /tmp/mediamtx.tar.gz \
    && echo "${MEDIAMTX_SHA256}  /tmp/mediamtx.tar.gz" | sha256sum -c - \
    && mkdir /tmp/mediamtx \
    && tar -xzf /tmp/mediamtx.tar.gz -C /tmp/mediamtx \
    && install -m 0755 /tmp/mediamtx/mediamtx /usr/local/bin/mediamtx \
    && mkdir -p /usr/share/licenses/mediamtx \
    && cp /tmp/mediamtx/LICENSE /usr/share/licenses/mediamtx/LICENSE \
    && python3 -c "from kcp.extension import KCP; KCP(1)" \
    && ffmpeg -hide_banner -demuxers 2>&1 | grep hevc >/dev/null \
    && ffmpeg -hide_banner -muxers 2>&1 | grep rtsp >/dev/null \
    && mediamtx --version \
    && apk del .build-deps \
    && rm -rf /tmp/requirements.txt /tmp/mediamtx /tmp/mediamtx.tar.gz

COPY bridge /opt/bridge
COPY run.sh /run.sh
RUN chmod 0755 /run.sh
WORKDIR /opt/bridge
CMD ["/run.sh"]
