# Installing PJSIP with Python Bindings on Ubuntu/Debian

This guide walks you through compiling PJSIP from source with Python (pjsua2) bindings enabled.

## Prerequisites

### 1. Install System Dependencies

```bash
# Update package lists
sudo apt update

# Install build essentials
sudo apt install -y build-essential python3-dev python3-pip

# Install PJSIP dependencies
sudo apt install -y \
    libasound2-dev \
    libssl-dev \
    libopus-dev \
    libspeex-dev \
    libspeexdsp-dev \
    libsndfile1-dev \
    libv4l-dev \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavfilter-dev \
    libavutil-dev \
    libswresample-dev \
    libswscale-dev \
    libvpx-dev \
    libx264-dev

# Install SWIG for Python bindings
sudo apt install -y swig
```

### 2. Verify Python Version

Ensure you have Python 3.10 or later:

```bash
python3 --version
# Should output: Python 3.10.x or higher
```

---

## Building PJSIP

### 1. Download PJSIP Source

```bash
# Create build directory
mkdir -p ~/pjsip-build && cd ~/pjsip-build

# Download latest stable release (check https://github.com/pjsip/pjproject/releases)
PJSIP_VERSION="2.14.1"
wget https://github.com/pjsip/pjproject/archive/refs/tags/${PJSIP_VERSION}.tar.gz

# Extract
tar -xzf ${PJSIP_VERSION}.tar.gz
cd pjproject-${PJSIP_VERSION}
```

### 2. Configure Build Options

Create a custom configuration file:

```bash
cat > pjlib/include/pj/config_site.h << 'EOF'
/* Enable required features */
#define PJMEDIA_HAS_VIDEO 0
#define PJ_HAS_IPV6 1

/* Audio codec settings */
#define PJMEDIA_HAS_SPEEX_CODEC 1
#define PJMEDIA_HAS_OPUS_CODEC 1
#define PJMEDIA_HAS_G711_CODEC 1

/* Increase max calls if needed */
#define PJSUA_MAX_CALLS 8

/* Python compatibility */
#define PJ_IS_LITTLE_ENDIAN 1
#define PJ_IS_BIG_ENDIAN 0
EOF
```

### 3. Configure and Build

```bash
# Configure with Python support
./configure \
    --enable-shared \
    --disable-video \
    --with-opus \
    --with-speex \
    CFLAGS="-fPIC -O2" \
    CXXFLAGS="-fPIC -O2"

# Build (use -j with number of CPU cores)
make dep
make -j$(nproc)
```

### 4. Build Python Bindings

```bash
cd pjsip-apps/src/swig/python

# Generate SWIG wrappers
make

# Build the Python module
python3 setup.py build
```

### 5. Install Python Module

```bash
# Install system-wide (requires sudo)
sudo python3 setup.py install

# OR install to user directory
python3 setup.py install --user
```

---

## Verify Installation

```bash
# Test import
python3 -c "import pjsua2; print('pjsua2 imported successfully!')"

# Check version
python3 -c "import pjsua2 as pj; ep = pj.Endpoint(); ep.libCreate(); print(f'PJSIP Version: {ep.libVersion().full}')"
```

Expected output:
```
pjsua2 imported successfully!
PJSIP Version: 2.14.1
```

---

## Troubleshooting

### "No module named pjsua2"

1. Check Python version matches what was used to build:
   ```bash
   python3 --version
   which python3
   ```

2. Rebuild with correct Python:
   ```bash
   cd pjsip-apps/src/swig/python
   /usr/bin/python3.10 setup.py install --user
   ```

### SWIG version mismatch

Install SWIG 4.x or later:
```bash
sudo apt install swig4.0
# OR build from source
```

### Missing audio device

Install additional audio libraries:
```bash
sudo apt install -y pulseaudio libpulse-dev
# Reconfigure and rebuild
./configure --with-pa
make clean && make dep && make -j$(nproc)
```

### OpenSSL issues

```bash
# Install OpenSSL dev package
sudo apt install -y libssl-dev

# Reconfigure
./configure --with-ssl
```

### Permission denied on install

Use `--user` flag or create a virtual environment:
```bash
python3 -m venv ~/klara-venv
source ~/klara-venv/bin/activate
cd pjsip-apps/src/swig/python
python setup.py install
```

---

## Optional: Using with Virtual Environment

If you want to use PJSIP with a virtual environment:

```bash
# Create venv
python3 -m venv ~/klara-venv
source ~/klara-venv/bin/activate

# Install PJSIP to venv
cd ~/pjsip-build/pjproject-*/pjsip-apps/src/swig/python
python setup.py install

# Verify
python -c "import pjsua2; print('OK')"

# Install other dependencies
pip install -r /path/to/klara/requirements.txt
```

---

## Quick Reference: Complete Installation Script

Save this as `install_pjsip.sh` and run with `bash install_pjsip.sh`:

```bash
#!/bin/bash
set -e

PJSIP_VERSION="2.14.1"

echo "=== Installing PJSIP ${PJSIP_VERSION} with Python bindings ==="

# Install dependencies
sudo apt update
sudo apt install -y \
    build-essential python3-dev python3-pip swig \
    libasound2-dev libssl-dev libopus-dev libspeex-dev libspeexdsp-dev

# Download and extract
mkdir -p ~/pjsip-build && cd ~/pjsip-build
wget -q https://github.com/pjsip/pjproject/archive/refs/tags/${PJSIP_VERSION}.tar.gz
tar -xzf ${PJSIP_VERSION}.tar.gz
cd pjproject-${PJSIP_VERSION}

# Configure
cat > pjlib/include/pj/config_site.h << 'EOF'
#define PJMEDIA_HAS_VIDEO 0
#define PJ_HAS_IPV6 1
#define PJMEDIA_HAS_G711_CODEC 1
#define PJMEDIA_HAS_OPUS_CODEC 1
EOF

./configure --enable-shared --disable-video CFLAGS="-fPIC" CXXFLAGS="-fPIC"

# Build
make dep
make -j$(nproc)

# Build Python bindings
cd pjsip-apps/src/swig/python
make
python3 setup.py install --user

# Verify
python3 -c "import pjsua2; print('SUCCESS: pjsua2 installed!')"

echo "=== PJSIP installation complete ==="
```

---

## Next Steps

After installing PJSIP:

1. Copy `.env.example` to `.env` and fill in your 3CX credentials
2. Install Python dependencies: `pip install -r requirements.txt`
3. Run the gateway: `python main.py`
