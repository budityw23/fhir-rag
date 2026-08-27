FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src ./src
# The CPU wheel index keeps torch from dragging in the nvidia-* CUDA wheels,
# which would add several GB to the image for no benefit: all-MiniLM-L6-v2 is
# small enough that CPU inference is well under a millisecond per chunk.
RUN pip install --no-cache-dir --prefix=/install \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        ".[semantic]"

FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /install /usr/local
# Bake the sentence-transformer weights into the image so the container never
# needs to reach HuggingFace at request time, and so a cold start cannot stall
# on a ~90MB download.
ENV HF_HOME=/opt/hf
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"
COPY src ./src
COPY db ./db
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
