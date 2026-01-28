#!/bin/bash
# Klara Voice Assistant - Quick Deploy Script for Raspberry Pi
# 
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/klara/main/deploy.sh | bash
#
# Or run locally after cloning:
#   ./deploy.sh

set -e

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Klara Voice Assistant - Raspberry Pi Deployment       ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo "Docker installed. Please log out and back in, then run this script again."
    exit 0
fi

# Check if docker compose is available
if ! docker compose version &> /dev/null; then
    echo "Docker Compose not found. Please update Docker or install docker-compose-plugin."
    exit 1
fi

# Create directory
INSTALL_DIR="${HOME}/klara"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo "Installing to: $INSTALL_DIR"

# Download docker-compose file
if [ ! -f "docker-compose.yml" ]; then
    echo "Downloading docker-compose.yml..."
    cat > docker-compose.yml << 'COMPOSE_EOF'
services:
  klara:
    image: gergoke68/klara:latest
    container_name: klara
    network_mode: host
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./system_instruction.txt:/app/system_instruction.txt:ro
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
COMPOSE_EOF
fi

# Create .env file if not exists
if [ ! -f ".env" ]; then
    echo ""
    echo "Creating .env file..."
    echo "Please enter your configuration:"
    echo ""
    
    read -p "SIP Extension (e.g., 1001): " SIP_EXTENSION
    read -sp "SIP Password: " SIP_PASSWORD
    echo ""
    read -p "SIP Server (e.g., pbx.example.com): " SIP_SERVER
    read -p "Gemini API Key: " GEMINI_API_KEY
    
    cat > .env << ENV_EOF
# Klara Voice Assistant Configuration
SIP_EXTENSION=${SIP_EXTENSION}
SIP_PASSWORD=${SIP_PASSWORD}
SIP_SERVER=${SIP_SERVER}
SIP_PORT=5060
SIP_TRANSPORT=udp

GEMINI_API_KEY=${GEMINI_API_KEY}
GEMINI_MODEL=gemini-2.0-flash-exp

LOG_LEVEL=INFO
ENV_EOF

    echo ".env file created!"
fi

# Create default system instruction if not exists
if [ ! -f "system_instruction.txt" ]; then
    echo "Klara is a helpful voice assistant." > system_instruction.txt
    echo "Respond naturally and conversationally in the language the user speaks." >> system_instruction.txt
    echo "Keep responses concise and friendly." >> system_instruction.txt
    echo "Default system_instruction.txt created (customize as needed)"
fi

echo ""
echo "Pulling latest image..."
docker compose pull

echo ""
echo "Starting Klara..."
docker compose up -d

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                  Deployment Complete!                      ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "Useful commands:"
echo "  View logs:     cd $INSTALL_DIR && docker compose logs -f"
echo "  Stop:          cd $INSTALL_DIR && docker compose down"
echo "  Restart:       cd $INSTALL_DIR && docker compose restart"
echo "  Update:        cd $INSTALL_DIR && docker compose pull && docker compose up -d"
echo ""
echo "Configuration files:"
echo "  .env                    - SIP and API credentials"
echo "  system_instruction.txt  - AI personality/instructions"
echo ""

# Show initial logs
echo "Initial logs:"
sleep 3
docker compose logs --tail 20
