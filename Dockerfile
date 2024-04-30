FROM python:3.11.7

WORKDIR /main

# Exit immediately if a command returns a non-zero exit status code
RUN set -xe

RUN apt-get update && \
    apt-get clean && \
    apt-get autoclean

# Install ffmpeg for developer-only YT downloading
RUN apt install ffmpeg -y

RUN pip3 install poetry
RUN poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main

COPY . .
CMD ["python3", "launcher.py"]
