FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY weather_high_tracker.py .

# Results (and optional Google credentials) are stored in /data,
# which docker-compose maps to ./data on your machine
ENV WEATHER_CSV=/data/weather_highs.csv \
    WEATHER_CREDS=/data/service_account.json
VOLUME /data

ENTRYPOINT ["python", "weather_high_tracker.py"]
