FROM hashicorp/terraform:light AS terraform


FROM python:3-alpine

ENV FLASK_APP main.py
ENV FLASK_DEBUG 0

ADD config /root/.ssh/config
ADD . /app
WORKDIR /app
RUN pip install -r requirements.txt \
  && mkdir -p /terraform \
  && apk add --no-cache git openssh

VOLUME /terraform

COPY --from=terraform /bin/terraform /bin/terraform
