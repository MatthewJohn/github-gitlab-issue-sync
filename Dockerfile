FROM python:3.12-slim

ARG http_proxy
ENV http_proxy=$http_proxy
ENV https_proxy=$http_proxy
ENV HTTP_PROXY=$http_proxy
ENV HTTPS_PROXY=$http_proxy

ADD requirements.txt .
RUN pip install -r requirements.txt

ADD *.py .

ENV http_proxy=
ENV https_proxy=
ENV HTTP_PROXY=
ENV HTTPS_PROXY=

ENTRYPOINT ["python", "-u", "server.py"]
