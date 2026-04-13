#!/usr/bin/env bash
set -euo pipefail

VM_HOST="root@85.9.198.137"
VM_KEY="${SSH_KEY:-$HOME/.ssh/google_compute_engine}"
COMPOSE_DIR="/opt/polybot"

echo "⏹  Stopping all PolyBot services on $VM_HOST..."
ssh -i "$VM_KEY" -o StrictHostKeyChecking=no "$VM_HOST" \
  "cd $COMPOSE_DIR && docker compose down"
echo "✅  All services stopped."
