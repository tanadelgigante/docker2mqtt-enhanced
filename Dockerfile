# Use a slim base image to reduce size
FROM python:3.11-slim-bullseye

# Set environment variables
ENV LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Install system dependencies and Docker CLI
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    gnupg-agent \
    software-properties-common \
    lsb-release && \
    # Add Docker repository
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    # Install Docker CLI
    apt-get update && \
    apt-get install --no-install-recommends -y docker-ce-cli && \
    # Clean up
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir paho-mqtt

# Create app directory structure
WORKDIR /app

# Copy source code
COPY src/docker2mqttenh.py /app/
RUN chmod +x /app/docker2mqttenh.py

# Set the entrypoint
ENTRYPOINT ["python3", "/app/docker2mqttenh.py"]