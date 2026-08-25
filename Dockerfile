FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /install /usr/local
COPY src ./src
COPY db ./db
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

