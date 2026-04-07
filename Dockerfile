FROM python:3.11-slim

WORKDIR /app

# 1. Install CPU-only PyTorch (small, ~200MB)
RUN pip install --no-cache-dir torch==2.1.0+cpu --index-url https://download.pytorch.org/whl/cpu

# 2. Install sentence-transformers WITHOUT deps (torch already installed)
RUN pip install --no-cache-dir --no-deps sentence-transformers==3.0.0

# 3. Install remaining deps (includes requests!)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

CMD ["python", "bot.py"]
