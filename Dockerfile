FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir requests jinja2

COPY gemma/ gemma/
COPY templates/ templates/

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "gemma"]
