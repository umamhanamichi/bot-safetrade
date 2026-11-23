# SafeTrade Auto-Sell Deposit Bot (Kryptex Payout Handler)

## 1. Tujuan Proyek
Membangun bot latar belakang (*background worker*) ringan menggunakan Python yang terhubung ke bursa **SafeTrade** melalui REST API dan/atau WebSocket. Bot ini bertugas memantau saldo kripto tertentu (misalnya hasil *payout mining* dari Kryptex) dan **secara otomatis mengeksekusi Market Sell Order ke pasangan USDT** segera setelah saldo melebihi batas minimum perdagangan (*minimum order amount*).

---

## 2. Instruksi untuk AI Agent (Execution Plan)
Jika Anda adalah AI Agent yang diminta untuk mengeksekusi proyek ini, lakukan langkah-langkah berikut secara berurutan:
1. Buat struktur direktori proyek sesuai bagian **Struktur File**.
2. Buat file `requirements.txt` dan instal dependensi yang dibutuhkan (`requests`, `python-dotenv`, `websocket-client`).
3. Buat file `.env.example` dan salin menjadi `.env` (minta pengguna mengisi API Key & Secret).
4. Implementasikan modul `safetrade_client.py` berdasarkan dokumentasi resmi SafeTrade API (Peatio / OpenDAX architecture).
5. Implementasikan `main.py` dengan logika *polling* saldo yang aman, penanganan *error*, pembulatan presisi desimal sesuai aturan pasar (*market precision*), dan pencatatan log (*logging*).
6. Berikan instruksi cara menjalankan skrip di latar belakang (*background service* / `systemd` / `pm2`).

---

## 3. Struktur File yang Harus Dibuat

```text
safetrade-autosell-bot/
├── .env.example          # Template konfigurasi environment
├── .gitignore            # Abaikan .env, venv, dan file log
├── requirements.txt      # Dependensi Python
├── safetrade_client.py   # Wrapper autentikasi HMAC & endpoint SafeTrade API
├── main.py               # Logika utama pemantauan saldo & eksekusi auto-sell
└── bot.log               # File log aktivitas transaksi (dibuat otomatis saat jalan)
```

---

## 4. Spesifikasi Teknis & API SafeTrade

SafeTrade menggunakan arsitektur **Peatio / OpenDAX REST API v2**.

* **Base URL REST API:** `https://safe.trade` (Verifikasi kembali terhadap dokumentasi resmi di `https://safetrade.com` apabila ada pembaruan endpoint).
* **Metode Autentikasi (Private Endpoints):**
  Menggunakan header autentikasi HMAC-SHA256 standar Peatio:
  * `X-Auth-Apikey`: API Key pengguna
  * `X-Auth-Nonce`: Timestamp dalam milidetik (`str(int(time.time() * 1000))`)
  * `X-Auth-Signature`: HMAC-SHA256 hex digest dari payload `nonce + api_key` menggunakan `API_SECRET`.

### Endpoint Kunci yang Digunakan:
1. **Cek Aturan Pasar (Precision & Min Amount):**
   * `GET /public/markets`
   * Mengambil `amount_precision`, `price_precision`, dan `min_amount` untuk pasangan pasar target (misal: `btcusdt`, `rvnusdt`, `ergusdt`, `kasusdt`).
2. **Cek Saldo Akun:**
   * `GET /account/balances` (Private)
   * Mengembalikan daftar aset beserta `currency` dan `balance` (saldo tersedia / *available*).
3. **Buat Order Jual (Market Sell):**
   * `POST /market/orders` (Private)
   * Parameter payload:
     * `market`: ID pasar huruf kecil (contoh: `btcusdt`)
     * `side`: `"sell"`
     * `ord_type`: `"market"`
     * `volume`: Jumlah koin yang akan dijual (dibulatkan ke bawah sesuai `amount_precision`).

---

## 5. Logika Utama (`main.py`)

Agent harus mengimplementasikan alur kerja berikut di dalam loop utama:

1. **Inisialisasi:**
   * Muat konfigurasi dari `.env` (`API_KEY`, `API_SECRET`, `TARGET_COIN`, `QUOTE_COIN`, `POLL_INTERVAL`, `DRY_RUN`).
   * Ambil metadata pasar dari `GET /public/markets` untuk mendapatkan nilai `min_amount` dan `amount_precision` dari pasangan `{TARGET_COIN}{QUOTE_COIN}`.
2. **Loop Pemantauan (Setiap `POLL_INTERVAL` detik, default 30 detik):**
   * Panggil `GET /account/balances` untuk mengecek saldo `available` dari `TARGET_COIN`.
   * Hitung volume yang valid dengan membulatkan ke bawah (*floor*) sesuai `amount_precision` pasar (gunakan `decimal.Decimal` dengan `ROUND_DOWN` agar tidak terkena error *insufficient balance*).
   * **Kondisi Pemicu:** Jika `valid_volume >= min_amount`:
     * Jika `DRY_RUN=true`: Catat log simulasi bahwa bot akan menjual `valid_volume` tanpa mengirim request POST.
     * Jika `DRY_RUN=false`: Kirim `POST /market/orders` dengan `side="sell"` dan `ord_type="market"`.
     * Catat respons order ID dan detail eksekusi ke konsol serta `bot.log`.
3. **Penanganan Error (Resilience):**
   * Gunakan blok `try...except` di dalam loop agar bot tidak berhenti (*crash*) jika terjadi gangguan jaringan sementara atau *rate limit* (HTTP 429).

---

## 6. Konfigurasi Environment (`.env.example`)

```env
# Kredensial API SafeTrade (WAJIB matikan izin Withdrawal!)
SAFETRADE_API_KEY=masukkan_api_key_anda
SAFETRADE_API_SECRET=masukkan_api_secret_anda

# Pengaturan Trading
TARGET_COIN=btc          # Koin yang dikirim dari Kryptex (contoh: btc, rvn, kas, erg)
QUOTE_COIN=usdt          # Koin tujuan hasil penjualan
POLL_INTERVAL=30         # Interval pengecekan saldo dalam detik

# Mode Keamanan (Ubah ke false jika sudah siap trading sungguhan)
DRY_RUN=true
```

---

## 7. Keamanan & Pengujian

1. **Izin API Key:** Saat membuat API Key di dashboard SafeTrade, **hanya aktifkan izin Read dan Trade**. Pastikan izin **Withdraw** dalam keadaan **NONAKTIF**.
2. **Wajib Dry-Run:** Jalankan pertama kali dengan `DRY_RUN=true` untuk memastikan autentikasi berhasil, aturan presisi pasar terbaca dengan benar, dan tidak ada bug pada perhitungan pembulatan desimal.
