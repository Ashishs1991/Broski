FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BROSKI_MODEL_PATH=/opt/broski-model
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed')" \
    && mkdir -p /opt/broski-model \
    && cp -aL /opt/fastembed/models--Qdrant--bge-small-en-v1.5-onnx-Q/snapshots/*/. /opt/broski-model/ \
    && rm -rf /opt/fastembed \
    && useradd --create-home broski
COPY app ./app
USER broski
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
