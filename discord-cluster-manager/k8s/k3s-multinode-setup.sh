#!/bin/bash
#
# Helper script for setting up k3s multi-node cluster
# Usage:
#   Server: ./k3s-multinode-setup.sh server
#   Agent:  ./k3s-multinode-setup.sh agent <server-ip> <token>
#
# Note: This script requires sudo/root access for installation.
# After installation, you can use kubectl as a regular user.

set -e

# Check if running with sudo
if [ "$EUID" -ne 0 ] && [ "$1" != "help" ] && [ "$1" != "--help" ] && [ "$1" != "-h" ]; then
    echo "Note: k3s installation requires sudo. The installation script will prompt for sudo."
    echo ""
fi

ROLE="${1:-help}"

if [ "$ROLE" = "help" ] || [ "$ROLE" = "--help" ] || [ "$ROLE" = "-h" ]; then
    echo "k3s Multi-Node Setup Helper"
    echo ""
    echo "Usage:"
    echo "  Server node: $0 server"
    echo "  Agent node:  $0 agent <server-ip> <token>"
    echo ""
    echo "Example:"
    echo "  # On first node (server):"
    echo "  $0 server"
    echo ""
    echo "  # On additional nodes (agents):"
    echo "  $0 agent 192.168.1.100 K10abc123def456ghi789"
    exit 0
fi

if [ "$ROLE" = "server" ]; then
    echo "=========================================="
    echo "Installing k3s Server"
    echo "=========================================="
    
    # Install k3s
    curl -sfL https://get.k3s.io | sh -
    
    # Wait for k3s to be ready
    echo "Waiting for k3s to start..."
    sleep 10
    
    # Get the node token
    TOKEN=$(sudo cat /var/lib/rancher/k3s/server/node-token)
    
    # Get server IP
    SERVER_IP=$(hostname -I | awk '{print $1}')
    
    # Set up kubectl
    mkdir -p ~/.kube
    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
    sudo chown $USER ~/.kube/config
    
    echo ""
    echo "=========================================="
    echo "Server installed successfully!"
    echo "=========================================="
    echo ""
    echo "Server IP: $SERVER_IP"
    echo "Node Token: $TOKEN"
    echo ""
    echo "To add agent nodes, run on each agent:"
    echo "  $0 agent $SERVER_IP $TOKEN"
    echo ""
    echo "Or manually:"
    echo "  K3S_TOKEN=$TOKEN \\"
    echo "  K3S_URL=https://$SERVER_IP:6443 \\"
    echo "  curl -sfL https://get.k3s.io | sh -"
    echo ""
    echo "Verifying installation..."
    kubectl get nodes
    
elif [ "$ROLE" = "agent" ]; then
    if [ -z "$2" ] || [ -z "$3" ]; then
        echo "Error: Server IP and token are required for agent setup"
        echo "Usage: $0 agent <server-ip> <token>"
        exit 1
    fi
    
    SERVER_IP="$2"
    TOKEN="$3"
    
    echo "=========================================="
    echo "Installing k3s Agent"
    echo "=========================================="
    echo "Server: $SERVER_IP"
    echo ""
    
    # Install k3s as agent
    K3S_TOKEN="$TOKEN" \
    K3S_URL="https://$SERVER_IP:6443" \
    curl -sfL https://get.k3s.io | sh -
    
    echo ""
    echo "=========================================="
    echo "Agent installed successfully!"
    echo "=========================================="
    echo ""
    echo "Verify from server node:"
    echo "  kubectl get nodes"
    
else
    echo "Error: Unknown role '$ROLE'"
    echo "Use 'server' or 'agent'"
    exit 1
fi

