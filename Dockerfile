FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Download torch wheel with wget (supports resume on connection drop)
# --tries=0 = unlimited retries, -c = resume partial download
RUN wget --tries=0 --retry-connrefused --timeout=60 -c \
    "https://download.pytorch.org/whl/cpu/torch-2.3.1%2Bcpu-cp311-cp311-linux_x86_64.whl" \
    -O /tmp/torch.whl && \
    wget --tries=0 --retry-connrefused --timeout=60 -c \
    "https://download.pytorch.org/whl/cpu/torchvision-0.18.1%2Bcpu-cp311-cp311-linux_x86_64.whl" \
    -O /tmp/torchvision.whl && \
    pip install --no-cache-dir /tmp/torch.whl /tmp/torchvision.whl && \
    rm /tmp/torch.whl /tmp/torchvision.whl

# Install everything else
RUN pip install --no-cache-dir --timeout=300 --retries=10 \
    fastapi==0.111.0 \
    uvicorn==0.30.1 \
    pydantic==2.7.1 \
    opencv-python-headless==4.9.0.80 \
    pandas==2.2.2 \
    numpy==1.26.4 \
    streamlit==1.35.0 \
    requests==2.32.3 \
    python-multipart==0.0.9 \
    httpx==0.27.0 \
    pytest==8.2.1 \
    pytest-asyncio==0.23.7 \
    ultralytics==8.2.18

COPY . .

RUN mkdir -p data/videos data/resources data/events
