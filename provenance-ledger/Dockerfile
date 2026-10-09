FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data
USER app
EXPOSE 8812
CMD ["uvicorn", "provenance_ledger.app:app", "--host", "0.0.0.0", "--port", "8812"]
