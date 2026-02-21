FROM python:3.11-slim

WORKDIR /app

COPY mcp-server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp-server/ .
COPY expressindex_core/ ./expressindex_core/

ENV PYTHONPATH=/app
ENV CONFIG_PATH=/app/config/settings.yaml

CMD ["python", "server.py"]
