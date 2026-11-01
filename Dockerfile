FROM python:3.11-slim

# FFmpeg + font dự phòng
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .
RUN mkdir -p nen_video meme video_da_duyet library/music library/sfx projects cache \
    && [ -f library/memes.json ] || echo "[]" > library/memes.json

EXPOSE 8000
# Trong container phải nghe 0.0.0.0 để máy ngoài truy cập được qua -p 8000:8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
