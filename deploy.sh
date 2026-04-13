#!/usr/bin/env bash
set -euo pipefail

VM2_IP="85.9.198.137"
VM2_USER="${VM2_USER:-ubuntu}"
REMOTE_DIR="/opt/polybot"
SSH_KEY="${SSH_KEY:-}"

SSH_CMD="ssh"
SCP_CMD="scp"
if [ -n "$SSH_KEY" ]; then
  SSH_CMD="ssh -i $SSH_KEY"
  SCP_CMD="scp -i $SSH_KEY"
fi

echo "=== PolyBot Deploy to VM2 ($VM2_IP) ==="

echo ">>> Copying source to VM2..."
$SSH_CMD "$VM2_USER@$VM2_IP" "mkdir -p $REMOTE_DIR"

rsync -avz --exclude 'node_modules' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.git' --exclude 'dist' \
  -e "${SSH_CMD}" \
  ./ "$VM2_USER@$VM2_IP:$REMOTE_DIR/"

echo ">>> Setting up .env on VM2..."
if [ ! -f ".env" ]; then
  echo "WARNING: No .env file found. Copying .env.example..."
  $SCP_CMD .env.example "$VM2_USER@$VM2_IP:$REMOTE_DIR/.env"
else
  $SCP_CMD .env "$VM2_USER@$VM2_IP:$REMOTE_DIR/.env"
fi

echo ">>> Starting Docker Compose on VM2..."
$SSH_CMD "$VM2_USER@$VM2_IP" "
  set -e
  cd $REMOTE_DIR
  
  if ! command -v docker &>/dev/null; then
    echo 'Installing Docker...'
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker \$USER || true
    newgrp docker || true
  fi

  docker compose down --remove-orphans 2>/dev/null || docker-compose down --remove-orphans 2>/dev/null || true
  docker compose build --no-cache 2>/dev/null || docker-compose build --no-cache
  docker compose up -d 2>/dev/null || docker-compose up -d
  
  echo ''
  echo '=== Container Status ==='
  docker compose ps 2>/dev/null || docker-compose ps
"

echo ""
echo "=== Deploy Complete! ==="
echo "Frontend: http://$VM2_IP"
echo "Backend API: http://$VM2_IP:8000/api/health"
echo "WebSocket: ws://$VM2_IP:8000/ws"
echo ""
echo "To check logs: ssh $VM2_USER@$VM2_IP 'cd $REMOTE_DIR && docker compose logs -f'"
