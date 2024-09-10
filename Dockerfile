FROM python:3.11.7

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    \
    PDM_CHECK_UPDATE=false

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    git \
    # deps for installing poetry
    build-essential \
    libcurl4-gnutls-dev \
    gnutls-dev \
    libmagic-dev \
    ffmpeg

RUN pip install -U pdm

WORKDIR /main
COPY pdm.lock pyproject.toml ./

RUN pdm install --check --prod --no-editable

COPY . .
ENTRYPOINT .venv/bin/python launcher.py
