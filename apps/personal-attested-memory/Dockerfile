FROM python:3.12-slim-bookworm
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 app
USER app
EXPOSE 9410
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9410/healthz', timeout=2)"
CMD ["uvicorn", "personal_memory.app:app", "--host", "0.0.0.0", "--port", "9410"]
