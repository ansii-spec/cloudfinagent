#!/usr/bin/env bash
set -e

# Change to project root directory
cd "$(dirname "$0")"

echo "=========================================="
echo " Starting EC2 Optimizer Stack"
echo "=========================================="

# Ensure .env exists
if [ ! -f .env ]; then
  echo "[-] .env not found. Creating from .env.example..."
  cp .env.example .env
fi

# Build and start all services in background
echo "[*] Launching containers (DB, Redis, API, Worker, Beat, Frontend)..."
docker compose up -d --build

# Wait briefly for API to be ready
echo "[*] Waiting for services to become healthy..."
RETRIES=30
while [ $RETRIES -gt 0 ]; do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    break
  fi
  sleep 1
  RETRIES=$((RETRIES - 1))
done

echo ""
echo "=========================================="
echo "  EC2 Optimizer is Running Successfully!"
echo "=========================================="
echo "  Web Application:  http://localhost:5173"
echo "  API Backend:      http://localhost:8000"
echo "  Swagger Docs:     http://localhost:8000/docs"
echo "=========================================="
echo ""
