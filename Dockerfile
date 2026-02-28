# ---- builder stage: compile native extensions ----
FROM python:3.11-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- runtime stage: slim image without compilers ----
FROM python:3.11-slim

WORKDIR /app

# Copy only the installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code (CSV files are now in Git, not LFS)
COPY . .

# Create runtime directories
RUN mkdir -p /app/data/sessions/history \
             /app/data/collection \
             /app/data/logs \
             /app/outputs \
             /app/logs

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
# Last updated: Fri Feb 27 21:03:01 CST 2026
