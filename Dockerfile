FROM python:3.12-slim

WORKDIR /app

# basic deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
EXPOSE 5000

# Run with Gunicorn (Flask app object is `app` inside app/watchforge.py)
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app.watchforge:app"]
