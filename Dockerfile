FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config.yaml ./config.yaml

RUN pip install --no-cache-dir -e .

CMD ["tg-grid", "run-all", "--config", "config.yaml"]
