FROM jrottenberg/ffmpeg:4.1-scratch AS ffmpeg

FROM python:3.11.7 AS builder
COPY --from=ffmpeg /bin/ffmpeg /usr/bin/ffmpeg

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    \
    # https://python-poetry.org/docs/configuration/#using-environment-variables
    POETRY_HOME="/opt/poetry" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=0

ENV PATH="$POETRY_HOME/bin:$PATH"

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    git \
    # deps for installing poetry
    curl \
    # deps for building python deps
    build-essential \
    libcurl4-gnutls-dev \
    gnutls-dev \
    libmagic-dev

RUN curl -sSL https://install.python-poetry.org | python -

WORKDIR /main
COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false
RUN poetry install --only main

COPY . .
ENTRYPOINT poetry run python -O launcher.py
