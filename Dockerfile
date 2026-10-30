# n8n + Python on Alpine, running as the non-root "node" user
FROM node:24-alpine

# System packages, Python 3 and build tools.
# py3-setuptools provides the "distutils" module that node-gyp needs
# to compile n8n's native parts (isolated-vm) on newer Python versions.
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-setuptools \
    python3-dev \
    build-base \
    graphicsmagick \
    tzdata \
    tini \
    ca-certificates

# Install n8n globally FIRST, using the system Python
# (pin a version with: --build-arg N8N_VERSION=2.21.7)
ARG N8N_VERSION=latest
RUN npm install -g n8n@${N8N_VERSION}

# Python virtual environment with the quant libraries
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir pandas yfinance backtesting

# Run as "node" so n8n stores its data in /home/node/.n8n,
# which is where the n8n_data volume is mounted
USER node
ENV HOME=/home/node
WORKDIR /home/node

EXPOSE 5678
ENTRYPOINT ["tini", "--"]
CMD ["n8n"]