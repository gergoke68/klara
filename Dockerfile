# Voice Assistant Gateway - Docker Image
# Multi-stage build: compile PJSIP, then create runtime image

# =============================================================================
# Stage 1: Build PJSIP with Python bindings
# =============================================================================
FROM python:3.11-slim-bookworm AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    swig \
    libasound2-dev \
    libssl-dev \
    libopus-dev \
    libspeex-dev \
    libspeexdsp-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set PJSIP version
ARG PJSIP_VERSION=2.14.1

# Download and extract PJSIP
WORKDIR /build
RUN wget -q https://github.com/pjsip/pjproject/archive/refs/tags/${PJSIP_VERSION}.tar.gz \
    && tar -xzf ${PJSIP_VERSION}.tar.gz \
    && rm ${PJSIP_VERSION}.tar.gz

WORKDIR /build/pjproject-${PJSIP_VERSION}

# Create config file
RUN cat > pjlib/include/pj/config_site.h << 'EOF'
#define PJMEDIA_HAS_VIDEO 0
#define PJ_HAS_IPV6 1
#define PJMEDIA_HAS_G711_CODEC 1
#define PJMEDIA_HAS_OPUS_CODEC 1
#define PJMEDIA_HAS_SPEEX_CODEC 1
#define PJSUA_MAX_CALLS 8
EOF

# Configure and build PJSIP
RUN ./configure \
    --enable-shared \
    --disable-video \
    --with-opus \
    --with-speex \
    CFLAGS="-fPIC -O2" \
    CXXFLAGS="-fPIC -O2" \
    && make dep \
    && make -j$(nproc)

# Build Python bindings
WORKDIR /build/pjproject-${PJSIP_VERSION}/pjsip-apps/src/swig/python
RUN make && python3 setup.py build

# =============================================================================
# Stage 2: Runtime image
# =============================================================================
FROM python:3.11-slim-bookworm AS runtime

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libasound2 \
    libssl3 \
    libopus0 \
    libspeex1 \
    libspeexdsp1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -s /bin/bash klara

# Copy PJSIP Python bindings from builder
COPY --from=builder /build/pjproject-*/pjsip-apps/src/swig/python/build/lib.*/* /usr/local/lib/python3.11/site-packages/

# Copy PJSIP shared libraries
COPY --from=builder /build/pjproject-*/pjlib/lib/*.so* /usr/local/lib/
COPY --from=builder /build/pjproject-*/pjlib-util/lib/*.so* /usr/local/lib/
COPY --from=builder /build/pjproject-*/pjmedia/lib/*.so* /usr/local/lib/
COPY --from=builder /build/pjproject-*/pjnath/lib/*.so* /usr/local/lib/
COPY --from=builder /build/pjproject-*/pjsip/lib/*.so* /usr/local/lib/
COPY --from=builder /build/pjproject-*/third_party/lib/*.so* /usr/local/lib/

# Update library cache
RUN ldconfig

# Set up application directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py config.py sip_client.py gemini_client.py audio_bridge.py tools.py system_instruction.txt ./

# Change ownership to non-root user
RUN chown -R klara:klara /app

# Switch to non-root user
USER klara

# Health check (verify pjsua2 import)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import pjsua2; print('OK')" || exit 1

# Environment variables (override in docker-compose or run command)
ENV SIP_EXTENSION=""
ENV SIP_PASSWORD=""
ENV SIP_SERVER=""
ENV SIP_PORT="5060"
ENV SIP_TRANSPORT="udp"
ENV GEMINI_API_KEY=""
ENV GEMINI_MODEL="gemini-2.0-flash-exp"
ENV LOG_LEVEL="INFO"

# Run the application
CMD ["python", "-u", "main.py"]
