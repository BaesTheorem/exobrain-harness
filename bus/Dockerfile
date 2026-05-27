FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
COPY web/ ./web/

# SQLite lives on a mounted volume so data survives restarts/deploys.
ENV BUS_DB=/data/bus.db
EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
