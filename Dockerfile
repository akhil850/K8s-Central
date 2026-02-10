FROM python:3.9-slim

WORKDIR /app

# 1. Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 2. Install AWS CLI v2
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip

# 3. Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && chmod +x kubectl \
    && mv kubectl /usr/local/bin/

# 4. Install aws-iam-authenticator
RUN curl -Lo aws-iam-authenticator https://github.com/kubernetes-sigs/aws-iam-authenticator/releases/download/v0.6.11/aws-iam-authenticator_0.6.11_linux_amd64 \
    && chmod +x aws-iam-authenticator \
    && mv aws-iam-authenticator /usr/local/bin/

# 5. THE MAGIC SHIM
# Ensures "aws-vault exec..." commands work inside Docker
RUN echo '#!/bin/sh\n\
if [ "$1" = "exec" ]; then\n\
    shift 3\n\
fi\n\
exec "$@"' > /usr/local/bin/aws-vault \
    && chmod +x /usr/local/bin/aws-vault

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Create folders so Docker has a place to mount
RUN mkdir -p configs data && chmod 777 configs data

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]