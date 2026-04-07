FROM python:3.11-slim

WORKDIR /app

# Install CPU-only PyTorch first (much smaller, ~200MB vs 3GB)
RUN pip install --no-cache-dir torch==2.1.0+cpu --index-url https://download.pytorch.org/whl/cpu

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

CMD ["python", "bot.py"]
