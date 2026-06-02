FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN wget --tries=0 --retry-connrefused --timeout=60 -c \
    "https://download.pytorch.org/whl/cpu/torch-2.3.1%2Bcpu-cp311-cp311-linux_x86_64.whl" \
    -O /tmp/torch-2.3.1+cpu-cp311-cp311-linux_x86_64.whl && \
    wget --tries=0 --retry-connrefused --timeout=60 -c \
    "https://download.pytorch.org/whl/cpu/torchvision-0.18.1%2Bcpu-cp311-cp311-linux_x86_64.whl" \
    -O /tmp/torchvision-0.18.1+cpu-cp311-cp311-linux_x86_64.whl && \
    pip install --no-cache-dir \
    /tmp/torch-2.3.1+cpu-cp311-cp311-linux_x86_64.whl \
    /tmp/torchvision-0.18.1+cpu-cp311-cp311-linux_x86_64.whl && \
    rm /tmp/torch-2.3.1+cpu-cp311-cp311-linux_x86_64.whl \
       /tmp/torchvision-0.18.1+cpu-cp311-cp311-linux_x86_64.whl

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