# Klara - Voice Assistant Gateway

> Connect your 3CX PBX to Google Gemini 2.0 Flash for real-time Hungarian voice AI

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Get Google Gemini API Key](#2-get-google-gemini-api-key)
3. [Configure 3CX Extension](#3-configure-3cx-extension)
4. [Deploy the Gateway](#4-deploy-the-gateway)
   - [Option A: Docker (Recommended)](#option-a-docker-recommended)
   - [Option B: Native Installation](#option-b-native-installation)
5. [Test Your Setup](#5-test-your-setup)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Prerequisites

### Hardware/Server Requirements

| Requirement | Minimum |
|-------------|---------|
| **OS** | Ubuntu 22.04 LTS / Debian 12 |
| **RAM** | 1 GB |
| **CPU** | 1 vCPU |
| **Network** | UDP ports 5060 + 10000-20000 open to 3CX |

### Software Requirements

- **Docker** (for Docker deployment) OR **Python 3.10+** (for native)
- **3CX PBX** (v18 or later) accessible from your server
- **Google Cloud account** with Gemini API access

### Network Configuration

Ensure your server can reach:
- Your 3CX server on port 5060 (SIP)
- UDP ports 10000-20000 (RTP media)
- `generativelanguage.googleapis.com` (Gemini API)

```bash
# Test 3CX connectivity
nc -zvu YOUR_3CX_IP 5060

# Test Gemini API connectivity
curl -I https://generativelanguage.googleapis.com
```

---

## 2. Get Google Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click **"Create API Key"**
4. Select or create a Google Cloud project
5. Copy the API key (starts with `AIza...`)

> [!IMPORTANT]
> Keep your API key secret! Never commit it to version control.

### Verify the API Key

```bash
curl "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_API_KEY"
```

You should see a list of available models.

---

## 3. Configure 3CX Extension

Create a dedicated extension in 3CX for the voice gateway.

### Step 3.1: Create New Extension

1. Log into your **3CX Management Console**
2. Go to **Users** (in the left sidebar)
3. Click **+ Add** to create a new user
4. Fill in:
   - **Extension Number**: e.g., `37214`
   - **First Name**: `Klára`
   - **Email**: (your email)
   - **Role**: `User`

### Step 3.2: Get SIP Credentials

In 3CX v18+, the SIP password is found in the **IP Phone** tab:

1. Open the user/extension you created
2. Click the **"IP Phone"** tab at the top
3. You'll see one of these options:
   - **Generic SIP Phone** section with credentials, OR
   - Click **"Add Phone"** → Select **"Generic SIP Phone"**
4. Note down:
   - **Extension Number**: e.g., `37214`
   - **Authentication ID**: (usually same as extension)
   - **Authentication Password**: The SIP password shown
   - **Domain/Server**: Your 3CX FQDN (e.g., `1882.3cx.cloud` from your URL)

> [!TIP]
> **Alternative**: Click the **"QR Code"** button on the General tab and decode it - it contains all SIP credentials.

> [!NOTE]
> If you don't see the password, click **"Reset password"** on the General tab to generate a new SIP password.

### Step 3.3: Find Your 3CX Server Address

Your SIP server address is your 3CX FQDN. You can find it:
- In the browser URL when logged into 3CX (e.g., `1882.3cx.cloud`)
- In **Settings → General → FQDN**

For your `.env` file, use:
```env
SIP_SERVER=1882.3cx.cloud
SIP_PORT=5060
```

---

## 4. Deploy the Gateway

Choose **one** deployment method:

---

### Option A: Docker (Recommended)

#### Step A.1: Clone/Copy the Project

```bash
# On your Linux server
mkdir -p /opt/klara && cd /opt/klara

# Copy all project files here (or git clone)
```

#### Step A.2: Configure Environment

```bash
cp .env.example .env
nano .env
```

Fill in your values:

```env
# 3CX Configuration
SIP_EXTENSION=1099
SIP_PASSWORD=your_sip_password_from_3cx
SIP_SERVER=192.168.1.100
SIP_PORT=5060
SIP_TRANSPORT=udp

# Gemini API
GEMINI_API_KEY=AIza...your_key_here
GEMINI_MODEL=gemini-2.0-flash-exp

# Logging
LOG_LEVEL=INFO
```

#### Step A.3: Build and Start

```bash
# Build the image (5-10 minutes for PJSIP compilation)
docker compose build

# Start the gateway
docker compose up -d

# View logs
docker compose logs -f
```

#### Step A.4: Verify Running

```bash
docker compose ps
# Should show: klara-voice-gateway ... Up (healthy)
```

---

### Option B: Native Installation

#### Step B.1: Install System Dependencies

```bash
sudo apt update
sudo apt install -y \
    build-essential \
    python3-dev \
    python3-pip \
    python3-venv \
    swig \
    libasound2-dev \
    libssl-dev \
    libopus-dev \
    libspeex-dev \
    libspeexdsp-dev \
    wget
```

#### Step B.2: Build PJSIP

```bash
# Download PJSIP
cd /tmp
wget https://github.com/pjsip/pjproject/archive/refs/tags/2.14.1.tar.gz
tar -xzf 2.14.1.tar.gz
cd pjproject-2.14.1

# Configure
cat > pjlib/include/pj/config_site.h << 'EOF'
#define PJMEDIA_HAS_VIDEO 0
#define PJ_HAS_IPV6 1
#define PJMEDIA_HAS_G711_CODEC 1
#define PJMEDIA_HAS_OPUS_CODEC 1
EOF

./configure --enable-shared --disable-video CFLAGS="-fPIC" CXXFLAGS="-fPIC"
make dep && make -j$(nproc)

# Build Python bindings
cd pjsip-apps/src/swig/python
make
python3 setup.py install --user
```

#### Step B.3: Setup Application

```bash
# Create directory
sudo mkdir -p /opt/klara
sudo chown $USER:$USER /opt/klara
cd /opt/klara

# Copy project files here

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
nano .env  # Fill in your values
```

#### Step B.4: Create Systemd Service

```bash
sudo tee /etc/systemd/system/klara.service << 'EOF'
[Unit]
Description=Klara Voice Assistant Gateway
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/opt/klara
Environment=PATH=/opt/klara/venv/bin
ExecStart=/opt/klara/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable klara
sudo systemctl start klara

# Check status
sudo systemctl status klara
```

---

## 5. Test Your Setup

### Step 5.1: Check Registration

Look for this in the logs:
```
SIP registration successful (expires: 300s)
Voice Assistant Gateway is READY
Extension: 1099
```

Also verify in 3CX Management Console → Extensions that your extension shows as **"Registered"**.

### Step 5.2: Make a Test Call

1. From any phone connected to 3CX, dial the extension (e.g., `1099`)
2. The call should be auto-answered
3. Speak in Hungarian: *"Szia, ki vagy te?"*
4. You should hear a Hungarian response from Gemini

### Step 5.3: Test Function Calling

During a call, try:
- *"Mi a szerverek állapota?"* → Returns server status
- *"Állíts be egy emlékeztetőt: holnap 9-kor megbeszélés"* → Sets reminder

Check the logs for:
```
Tool called: get_service_status()
Reminder set: holnap 9-kor megbeszélés
```

---

## 6. Troubleshooting

### Registration Failed

```
SIP registration failed: 401 - Unauthorized
```

**Fix**: Check SIP_EXTENSION and SIP_PASSWORD in `.env`

---

### No Audio / One-Way Audio

**Causes**:
- Firewall blocking RTP ports (10000-20000 UDP)
- NAT issues

**Fix**:
```bash
# Open RTP ports
sudo ufw allow 10000:20000/udp
```

---

### "pjsua2 module not found"

**Fix** (Docker): Rebuild the image
```bash
docker compose build --no-cache
```

**Fix** (Native): Reinstall PJSIP Python bindings
```bash
cd /tmp/pjproject-*/pjsip-apps/src/swig/python
python3 setup.py install --user
```

---

### Gemini API Error

```
Error: API key not valid
```

**Fix**: Verify your API key at [AI Studio](https://aistudio.google.com/apikey)

---

### View Full Logs

```bash
# Docker
docker compose logs -f --tail 100

# Native
sudo journalctl -u klara -f
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Start (Docker) | `docker compose up -d` |
| Stop (Docker) | `docker compose down` |
| Logs (Docker) | `docker compose logs -f` |
| Rebuild (Docker) | `docker compose build --no-cache` |
| Start (Native) | `sudo systemctl start klara` |
| Stop (Native) | `sudo systemctl stop klara` |
| Logs (Native) | `sudo journalctl -u klara -f` |
