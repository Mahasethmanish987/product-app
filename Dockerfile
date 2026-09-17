FROM python:3.13-slim

# Build metadata, surfaced by GET /version. CI passes the branch and commit.
ARG SERVICE_VERSION=0.2.0
ARG GIT_COMMIT=unknown

ENV SERVICE_VERSION=$SERVICE_VERSION \
    GIT_COMMIT=$GIT_COMMIT \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

LABEL org.opencontainers.image.title="product-service" \
      org.opencontainers.image.revision=$GIT_COMMIT \
      org.opencontainers.image.version=$SERVICE_VERSION

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# The service is a package now, not a single file.
COPY app.py errors.py logging_config.py schemas.py store.py ./
COPY routers ./routers

# Run unprivileged; the chart's securityContext pins the same uid.
RUN useradd --system --uid 10001 --user-group --no-create-home appuser \
    && chown -R appuser:appuser /app
USER 10001

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
