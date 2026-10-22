# TODO (1 pm): this Dockerfile works, but it would not pass a review. Fix it:
#   1. "latest" changes under your feet: pin a slim Python 3.12 image (python:3.12-slim).
#   2. Copy requirements.txt first and install it, then copy server.py: the install layer is then cached.
#   3. The server runs as root: create an unprivileged user and switch to it with USER, before CMD.
#   4. Use the exec form for CMD, so the server receives the stop signal from the host.
FROM python:latest
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8000
CMD python server.py
