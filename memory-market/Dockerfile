FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY static ./static
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data
USER app
EXPOSE 8810
CMD ["uvicorn", "memory_market.app:app", "--host", "0.0.0.0", "--port", "8810"]
