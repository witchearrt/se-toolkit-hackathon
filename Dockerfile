FROM python:3.11-slim

ARG BUILD_TIME
ENV BUILD_TIME=${BUILD_TIME}

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
