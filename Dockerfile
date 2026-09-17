FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# The service is a package now, not a single file.
COPY app.py errors.py logging_config.py schemas.py store.py ./
COPY routers ./routers

# Build metadata surfaced by GET /version.
ARG SERVICE_VERSION=0.2.0
ARG GIT_COMMIT=unknown
ENV SERVICE_VERSION=$SERVICE_VERSION \
    GIT_COMMIT=$GIT_COMMIT

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
