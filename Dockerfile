# syntax = docker/dockerfile:1.0.0-experimental
FROM python:3.9.6-slim-bullseye

# Definition of a Device & Service
ENV POSITION=Runtime \
    SERVICE=azure-face-api-registrator-python-kube \
    AION_HOME=/var/lib/aion

# Setup Directoties
RUN mkdir -p /${AION_HOME}/$POSITION/$SERVICE

WORKDIR /${AION_HOME}/$POSITION/$SERVICE

RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    git \
    openssh-client \
    libmariadb-dev \
    build-essential \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

ADD . .

# Install dependencies
RUN pip3 install --upgrade pip
RUN git config --global url."git@bitbucket.org:".insteadOf "https://bitbucket.org/"
RUN mkdir -p /root/.ssh/ && touch /root/.ssh/known_hosts && ssh-keyscan -t rsa bitbucket.org >> /root/.ssh/known_hosts
RUN --mount=type=secret,id=ssh,target=/root/.ssh/id_rsa pip3 install -r requirements.txt

CMD ["sh", "entrypoint.sh"]


