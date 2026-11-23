# SafeTrade Auto-Sell Bot — Docker Deployment Guide

## Deploy ke VPS (Docker)

### 1. Clone repo di VPS
```bash
git clone <YOUR_REPO_URL> bot-safetrade
cd bot-safetrade
```

### 2. Buat file .env
```bash
cp .env.example .env
nano .env   # isi API key, secret, dan konfigurasi lainnya
```

### 3. Cek IP publik VPS (untuk whitelist di SafeTrade)
```bash
curl https://api.ipify.org
```
Tambahkan IP ini ke **Trusted IP Addresses** di dashboard SafeTrade:
`Profile → API Keys → Edit → Trusted IP Addresses`

### 4. Jalankan bot
```bash
docker compose up -d
```

### 5. Cek status & log
```bash
# Status container
docker compose ps

# Log real-time
docker compose logs -f

# Log dari file (persisten di ./logs/bot.log)
tail -f logs/bot.log
```

### 6. Perintah umum lainnya
```bash
# Stop bot
docker compose down

# Restart bot (misal setelah update .env)
docker compose restart

# Update kode & rebuild image
git pull
docker compose up -d --build
```

---

## Keunggulan Docker di VPS

- **IP statis** — VPS punya IP tetap, tidak perlu update whitelist SafeTrade setiap saat
- **Auto-restart** — container otomatis restart jika crash atau VPS reboot (`restart: unless-stopped`)
- **Log persisten** — log tersimpan di `./logs/bot.log` di luar container, tidak hilang saat container restart
