FROM python:3.12-slim

# Install system dependencies including FFmpeg for video processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libvpx-dev \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specifications and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY bot/ bot/
COPY pytest.ini .

# Create volume mount point for database and temp directory
RUN mkdir -p /app/data /tmp/stickbot

ENV PYTHONPATH=/app
ENV DB_PATH=/app/data/bot.db
ENV TEMP_DIR=/tmp/stickbot
ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "-m", "bot.main"]
