# syntax=docker/dockerfile:1

FROM python:3.10.2

# Exit immediately if a command returns a non-zero exit status code
RUN set -xe

RUN apt-get update && \
    apt-get clean && \
    apt-get autoclean

# Install ffmpeg for developer-only YT downloading
RUN apt install ffmpeg -y

WORKDIR /main

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt --no-cache-dir --force-reinstall

COPY . .

RUN chmod +x wait-for-it.sh
CMD ["python3", "main.py"]