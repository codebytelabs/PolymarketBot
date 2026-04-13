#!/usr/bin/env bash
set -euo pipefail

VM_HOST="root@85.9.198.137"
VM_KEY="${SSH_KEY:-$HOME/.ssh/google_compute_engine}"
COMPOSE_DIR="/opt/polybot"

echo "🔄  Restarting all PolyBot services on $VM_HOST..."
ssh -i "$VM_KEY" -o StrictHostKeyChecking=no "$VM_HOST" \
  "cd $COMPOSE_DIR && docker compose down && docker compose up -d --build"
echo ""
echo "✅  Services restarted. Checking health..."
sleep 5
ssh -i "$VM_KEY" -o StrictHostKeyChecking=no "$VM_HOST" \
  "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep polybot"
