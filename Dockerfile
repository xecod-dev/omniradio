FROM python:3-alpine

# Install ffmpeg, curl, and runtime libraries
RUN apk add --no-cache ffmpeg curl bash tzdata

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# Environment defaults
ENV AUDIO_DIR=/app/audio
ENV CONFIG_FILE=/app/config/stations.json
ENV PORT=9000

# Expose HTTP port 9000, FTP port 2121, and passive FTP ports 2122-2125
EXPOSE 9000 2121 2122 2123 2124 2125

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:9000/healthz || exit 1

CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "9000"]
