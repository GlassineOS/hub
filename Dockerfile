# SPDX-License-Identifier: GPL-2.0-or-later
# The app. It holds no credentials and no host rights: everything of that kind is a
# request to hubd over the socket compose mounts.
FROM node:24-slim AS vendor
WORKDIR /b
COPY app/fetch-vendor.sh app/fetch-vendor.sh
RUN mkdir -p app/hub/static && app/fetch-vendor.sh

FROM python:3.13-slim
ENV PIP_ROOT_USER_ACTION=ignore PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends git ca-certificates >/dev/null \
    && pip install -q mcp==2.3.0 starlette==1.10.0 uvicorn==0.54.0 websockets==17.4 onnxruntime==1.31.1 \
    # the same commit of the search package the docs CI builds its index with
    && pip install -q "glassine-docs @ git+https://github.com/GlassineOS/search@7ffb0a9f024b87b0744b0378186e16592d4d3176" \
    && apt-get purge -y -qq git >/dev/null && apt-get autoremove -y -qq >/dev/null && rm -rf /var/lib/apt/lists
WORKDIR /srv/hub
COPY app/hub app/hub
COPY --from=vendor /b/app/hub/static/vendor app/hub/static/vendor
COPY config config
ENV HUB_CONFIG=/srv/hub/config/repos.toml HUB_CACHE=/cache HOME=/tmp PYTHONPATH=/srv/hub/app
EXPOSE 9094 9095
CMD ["python", "-m", "hub.main"]
