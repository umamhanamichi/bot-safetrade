"""
main.py

Logika utama pemantauan saldo dan eksekusi auto-sell untuk
SafeTrade Auto-Sell Deposit Bot (Kryptex Payout Handler).

Alur:
1. Muat konfigurasi dari .env
2. Ambil metadata pasar (amount_precision, min_amount) sekali di awal
3. Loop setiap POLL_INTERVAL detik:
   - Cek saldo available TARGET_COIN
   - Hitung volume valid (floor sesuai amount_precision)
   - Jika valid_volume >= min_amount -> eksekusi (atau simulasikan) market sell
4. Resilient terhadap error jaringan / rate limit (tidak crash)
"""

import logging
import os
import sys
import time
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from dotenv import load_dotenv

from safetrade_client import RateLimitError, SafeTradeAPIError, SafeTradeClient

# ----------------------------------------------------------------------
# Setup logging: tulis ke konsol dan ke bot.log
# ----------------------------------------------------------------------
# Tulis log ke /app/logs/bot.log jika berjalan di dalam Docker
# (direktori /app/logs di-mount sebagai volume), fallback ke bot.log
# di direktori saat ini jika berjalan langsung (development lokal).
_LOG_DIR = "/app/logs" if os.path.isdir("/app/logs") else "."
_LOG_FILE = os.path.join(_LOG_DIR, "bot.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")


def load_config() -> dict:
    """Muat dan validasi konfigurasi dari .env."""
    load_dotenv()

    api_key = os.getenv("SAFETRADE_API_KEY", "").strip()
    api_secret = os.getenv("SAFETRADE_API_SECRET", "").strip()
    public_base_url = os.getenv(
        "SAFETRADE_PUBLIC_BASE_URL", "https://safe.trade/api/v2/peatio"
    ).strip()
    private_base_url = os.getenv(
        "SAFETRADE_PRIVATE_BASE_URL", "https://safe.trade/api/v2/trade"
    ).strip()
    target_coin = os.getenv("TARGET_COIN", "").strip().lower()
    quote_coin = os.getenv("QUOTE_COIN", "").strip().lower()
    poll_interval = int(os.getenv("POLL_INTERVAL", "30"))
    dry_run = os.getenv("DRY_RUN", "true").strip().lower() in ("1", "true", "yes")

    missing = [
        name
        for name, value in [
            ("SAFETRADE_API_KEY", api_key),
            ("SAFETRADE_API_SECRET", api_secret),
            ("TARGET_COIN", target_coin),
            ("QUOTE_COIN", quote_coin),
        ]
        if not value
    ]
    if missing:
        logger.error("Konfigurasi .env tidak lengkap, hilang: %s", ", ".join(missing))
        sys.exit(1)

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "public_base_url": public_base_url,
        "private_base_url": private_base_url,
        "target_coin": target_coin,
        "quote_coin": quote_coin,
        "poll_interval": poll_interval,
        "dry_run": dry_run,
    }


def floor_to_precision(value: Decimal, precision: int) -> Decimal:
    """Bulatkan value ke bawah (floor) sesuai jumlah desimal `precision`."""
    quantum = Decimal(1).scaleb(-precision) if precision > 0 else Decimal(1)
    return value.quantize(quantum, rounding=ROUND_DOWN)


def fetch_market_rules(client: SafeTradeClient, market_id: str) -> dict:
    """Ambil amount_precision dan min_amount untuk market_id dari /public/markets."""
    market_info = client.get_market_info(market_id)

    amount_precision = int(
        market_info.get("amount_precision", market_info.get("base_precision", 8))
    )
    min_amount = Decimal(str(market_info.get("min_amount", "0")))

    logger.info(
        "Aturan pasar '%s' -> amount_precision=%s, min_amount=%s",
        market_id,
        amount_precision,
        min_amount,
    )
    return {"amount_precision": amount_precision, "min_amount": min_amount}


def get_available_balance(client: SafeTradeClient, currency: str) -> Decimal:
    """Ambil saldo 'available' untuk currency tertentu. Mengembalikan 0 jika tidak ada."""
    entry = client.get_balance_for(currency)
    if entry is None:
        return Decimal("0")

    raw_balance = entry.get("balance", entry.get("available", "0"))
    try:
        return Decimal(str(raw_balance))
    except InvalidOperation:
        logger.warning("Gagal parse saldo '%s' dari respons: %s", currency, raw_balance)
        return Decimal("0")


def run_cycle(client: SafeTradeClient, config: dict, market_rules: dict, market_id: str) -> None:
    """Jalankan satu siklus pengecekan saldo + eksekusi (atau simulasi) sell order."""
    available_balance = get_available_balance(client, config["target_coin"])

    valid_volume = floor_to_precision(available_balance, market_rules["amount_precision"])

    logger.info(
        "Saldo %s tersedia: %s | volume valid (precision=%s): %s | min_amount: %s",
        config["target_coin"].upper(),
        available_balance,
        market_rules["amount_precision"],
        valid_volume,
        market_rules["min_amount"],
    )

    if valid_volume < market_rules["min_amount"] or valid_volume <= 0:
        logger.info("Saldo belum mencapai min_amount, menunggu siklus berikutnya.")
        return

    if config["dry_run"]:
        logger.info(
            "[DRY_RUN] Akan menjual %s %s di pasar '%s' (ord_type=market, side=sell). "
            "Tidak ada request POST yang dikirim.",
            valid_volume,
            config["target_coin"].upper(),
            market_id,
        )
        return

    try:
        order_response = client.create_market_sell_order(market_id, str(valid_volume))
        logger.info(
            "Order BERHASIL dibuat -> market=%s volume=%s | respons: %s",
            market_id,
            valid_volume,
            order_response,
        )
    except RateLimitError:
        logger.warning("Rate limit (HTTP 429) saat membuat order, akan dicoba lagi siklus berikutnya.")
    except SafeTradeAPIError as exc:
        logger.error("Gagal membuat order: %s", exc)


def main() -> None:
    config = load_config()
    market_id = f"{config['target_coin']}{config['quote_coin']}"

    logger.info(
        "Memulai SafeTrade Auto-Sell Bot | market=%s | poll_interval=%ss | DRY_RUN=%s",
        market_id,
        config["poll_interval"],
        config["dry_run"],
    )

    client = SafeTradeClient(
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        public_base_url=config["public_base_url"],
        private_base_url=config["private_base_url"],
    )

    # Ambil metadata pasar di awal. Jika gagal, retry dengan backoff sederhana
    # sebelum menyerah sepenuhnya (tanpa aturan pasar, bot tidak bisa berjalan aman).
    market_rules = None
    for attempt in range(1, 6):
        try:
            market_rules = fetch_market_rules(client, market_id)
            break
        except (SafeTradeAPIError, ValueError) as exc:
            logger.error("Gagal mengambil metadata pasar (percobaan %s/5): %s", attempt, exc)
            time.sleep(min(5 * attempt, 30))

    if market_rules is None:
        logger.critical("Tidak dapat mengambil metadata pasar setelah beberapa percobaan. Keluar.")
        sys.exit(1)

    while True:
        try:
            run_cycle(client, config, market_rules, market_id)
        except RateLimitError:
            logger.warning("Rate limit (HTTP 429) terdeteksi, menunggu siklus berikutnya.")
        except SafeTradeAPIError as exc:
            logger.error("Error API SafeTrade: %s", exc)
        except Exception as exc:  # noqa: BLE001 - jaga agar bot tidak crash
            logger.exception("Error tak terduga dalam loop utama: %s", exc)

        time.sleep(config["poll_interval"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot dihentikan oleh pengguna (KeyboardInterrupt).")
