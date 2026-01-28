# Klara - Voice Assistant Gateway

<p align="center">
  <strong>3CX ↔ Google Gemini 2.0 Flash Voice AI Bridge</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#deployment">Deployment</a> •
  <a href="#development">Development</a>
</p>

---

Klara is a voice assistant gateway that connects your 3CX PBX system to Google Gemini 2.0 Flash AI. When someone calls your extension, Klara automatically answers and provides a natural conversational AI experience.

## Features

- 🎙️ **Real-time Voice AI** - Natural conversations powered by Gemini 2.0 Flash
- 📞 **3CX Integration** - Seamless SIP/VoIP connectivity
- 🔄 **Auto-Answer** - Automatically picks up incoming calls
- 🌍 **Multi-Language** - Responds in the caller's language
- 🐳 **Docker Ready** - Easy deployment with Docker
- 🍓 **Raspberry Pi** - Runs on ARM64 (Raspberry Pi 4+)

## Quick Start

### Docker Hub (Recommended)

Pull and run the pre-built image:

```bash
mkdir -p ~/klara && cd ~/klara

# Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
services:
  klara:
    image: gergoke68/klara:latest
    container_name: klara
    network_mode: host
    restart: unless-stopped
    env_file: .env
EOF

# Create .env with your credentials
cat > .env << 'EOF'
SIP_EXTENSION=1001
SIP_PASSWORD=your_sip_password
SIP_SERVER=your.3cx.server
SIP_PORT=5060
SIP_TRANSPORT=udp
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.0-flash-exp
LOG_LEVEL=INFO
EOF

# Run
docker compose pull
docker compose up -d
docker compose logs -f
```

### From Source

```bash
git clone https://github.com/YOUR_USERNAME/klara.git
cd klara
cp .env.example .env
# Edit .env with your credentials
docker compose up -d
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SIP_EXTENSION` | Your 3CX extension number | Required |
| `SIP_PASSWORD` | Extension authentication password | Required |
| `SIP_SERVER` | 3CX server hostname or IP | Required |
| `SIP_PORT` | SIP port | `5060` |
| `SIP_TRANSPORT` | Transport protocol: `udp`, `tcp`, `tls` | `udp` |
| `GEMINI_API_KEY` | Google Gemini API key | Required |
| `GEMINI_MODEL` | Gemini model to use | `gemini-2.0-flash-exp` |
| `LOG_LEVEL` | Logging level | `INFO` |

### Getting Your Credentials

#### 3CX SIP Credentials

1. Log in to your 3CX Management Console
2. Go to **Users** → Select your extension
3. Click on the **IP Phone** tab
4. Find the **SIP ID** (AuthID) and **Password**
5. **Important**: In the extension's **Options** tab, uncheck:
   - ☐ **Block remote non-tunnel connections (Insecure!)**
   
   > ⚠️ This setting blocks standard SIP connections. You must disable it for Klara to register.

#### Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Click **Create API Key**
3. Copy the key to your `.env` file

### Custom AI Personality

Create a `system_instruction.txt` file to customize the AI's personality:

```text
You are Klara, a friendly receptionist for Acme Corp.
Greet callers warmly and help them with their inquiries.
If they need to speak to a human, offer to transfer them.
Always be polite and professional.
```

Mount it in docker-compose:

```yaml
volumes:
  - ./system_instruction.txt:/app/system_instruction.txt:ro
```

## Deployment

### Raspberry Pi

The Docker image supports ARM64 architecture. On your Raspberry Pi 4 (or newer):

```bash
# Install Docker if not present
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in

# Deploy Klara
mkdir ~/klara && cd ~/klara
# Create docker-compose.yml and .env as shown above
docker compose up -d
```

### Linux Server

Works out of the box with `network_mode: host`:

```bash
docker compose up -d
```

### Windows/Mac (Docker Desktop)

> ⚠️ **Note**: Docker Desktop runs in a VM, so `network_mode: host` doesn't work properly for SIP. For testing only.

## Architecture

```
┌─────────────┐     SIP/RTP      ┌─────────────┐    WebSocket    ┌─────────────┐
│   3CX PBX   │ ←──────────────→ │    Klara    │ ←─────────────→ │   Gemini    │
│             │                  │   Gateway   │                 │  2.0 Flash  │
└─────────────┘                  └─────────────┘                 └─────────────┘
                                       │
                                 ┌─────┴─────┐
                                 │  Audio    │
                                 │  Bridge   │
                                 │ 8kHz↔16kHz│
                                 └───────────┘
```

## Development

### Prerequisites

- Python 3.11+
- PJSIP 2.14.1 with Python bindings
- Docker (for containerized development)

### Local Setup

```bash
# Install PJSIP (see docs/INSTALL_PJSIP.md)
# ...

# Install Python dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env

# Run
python main.py
```

### Building Docker Image

```bash
# Single architecture (local)
docker compose build

# Multi-architecture (for publishing)
docker buildx build --platform linux/amd64,linux/arm64 -t gergoke68/klara:latest --push .
```

## Troubleshooting

### Registration Failed

- Verify your SIP credentials in `.env`
- Check if 3CX firewall allows your IP
- Try `SIP_TRANSPORT=tcp` if UDP is blocked

### No Audio

- Ensure `network_mode: host` is set
- Check RTP ports aren't blocked by firewall
- Verify codec compatibility (G.711 μ-law recommended)

### Container Keeps Restarting

Check logs:
```bash
docker compose logs -f
```

Common issues:
- Missing or invalid API keys
- Network connectivity problems
- Invalid SIP credentials

## License

MIT License - See [LICENSE](LICENSE) for details.

## Acknowledgments

- [PJSIP](https://www.pjsip.org/) - SIP/VoIP stack
- [Google Gemini](https://deepmind.google/technologies/gemini/) - AI model
- [3CX](https://www.3cx.com/) - PBX system
