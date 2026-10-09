FROM python:3.12-alpine
WORKDIR /app
COPY server.py index.html ./
CMD ["python", "-u", "server.py"]
