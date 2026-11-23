# Gunakan image Python slim untuk ukuran image yang kecil
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependensi sistem yang dibutuhkan curl_cffi
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements terlebih dahulu (agar layer ini di-cache Docker,
# tidak perlu re-install setiap kali kode berubah)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY safetrade_client.py .
COPY main.py .

# Buat direktori untuk log (volume mount akan override ini di runtime)
RUN mkdir -p /app/logs

# Jalankan bot
CMD ["python", "-u", "main.py"]
