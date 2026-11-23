"""
safetrade_client.py

Wrapper autentikasi HMAC-SHA256 dan endpoint untuk SafeTrade API
(arsitektur Peatio / OpenDAX REST API v2).

Dokumentasi resmi: https://safetrade.com (verifikasi endpoint terbaru
apabila terjadi perubahan skema API).
"""

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional

try:
    # curl_cffi meniru TLS/JA3 fingerprint browser asli (Chrome/Firefox),
    # sehingga lebih tahan terhadap bot-detection Cloudflare dibanding
    # `requests` biasa (yang punya fingerprint khas Python).
    from curl_cffi import requests as requests  # type: ignore
    _USING_CURL_CFFI = True
except ImportError:  # pragma: no cover - fallback jika curl_cffi belum terinstall
    import requests  # type: ignore
    _USING_CURL_CFFI = False

logger = logging.getLogger("safetrade_client")

if _USING_CURL_CFFI:
    logger.info("Menggunakan curl_cffi (TLS impersonation) untuk HTTP client.")
else:
    logger.warning(
        "curl_cffi tidak ditemukan, fallback ke 'requests' biasa. "
        "Jika SafeTrade mengembalikan HTTP 403 dari Cloudflare, "
        "install curl_cffi: pip install curl_cffi"
    )


class SafeTradeAPIError(Exception):
    """Dilempar ketika SafeTrade API mengembalikan error response."""

    def __init__(self, status_code: int, message: str, payload: Optional[dict] = None):
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}
        super().__init__(f"[HTTP {status_code}] {message}")


class RateLimitError(SafeTradeAPIError):
    """Dilempar khusus untuk HTTP 429 (rate limit)."""


class SafeTradeClient:
    """
    Klien REST API SafeTrade.

    Menangani:
    - Endpoint publik (tidak butuh autentikasi), misal: GET /public/markets
    - Endpoint privat (butuh header HMAC-SHA256), misal:
      GET /account/balances, POST /market/orders
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        public_base_url: str = "https://safe.trade/api/v2/peatio",
        private_base_url: str = "https://safe.trade/api/v2/trade",
        timeout: int = 15,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        # SafeTrade memisahkan endpoint publik (metadata pasar) di bawah
        # prefix /api/v2/peatio, sedangkan endpoint privat (saldo akun &
        # order) ternyata dilayani di bawah prefix /api/v2/trade yang
        # berbeda (terkonfirmasi lewat trial-and-error terhadap backend).
        self.public_base_url = public_base_url.rstrip("/")
        self.private_base_url = private_base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session(impersonate="chrome") if _USING_CURL_CFFI else requests.Session()

    # ------------------------------------------------------------------
    # Autentikasi
    # ------------------------------------------------------------------
    def _build_auth_headers(self) -> Dict[str, str]:
        """
        Membangun header autentikasi standar Peatio:
          - X-Auth-Apikey   : API Key pengguna
          - X-Auth-Nonce    : timestamp dalam milidetik
          - X-Auth-Signature: HMAC-SHA256 hex digest dari (nonce + api_key)
                               menggunakan API_SECRET sebagai key.
        """
        nonce = str(int(time.time() * 1000))
        payload = f"{nonce}{self.api_key}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-Auth-Apikey": self.api_key,
            "X-Auth-Nonce": nonce,
            "X-Auth-Signature": signature,
        }

    # ------------------------------------------------------------------
    # HTTP helper internal
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        private: bool = False,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> Any:
        base_url = self.private_base_url if private else self.public_base_url
        url = f"{base_url}{path}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        if not _USING_CURL_CFFI:
            headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        if private:
            headers.update(self._build_auth_headers())

        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise SafeTradeAPIError(0, f"Network error: {exc}") from exc

        if response.status_code == 429:
            raise RateLimitError(429, "Rate limit exceeded", self._safe_json(response))

        if not response.ok:
            raise SafeTradeAPIError(
                response.status_code,
                f"Request failed: {response.text}",
                self._safe_json(response),
            )

        return self._safe_json(response)

    @staticmethod
    def _safe_json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    # ------------------------------------------------------------------
    # Endpoint publik
    # ------------------------------------------------------------------
    def get_markets(self) -> List[Dict[str, Any]]:
        """
        GET /public/markets

        Mengembalikan daftar pasar beserta metadata seperti
        amount_precision, price_precision, dan min_amount.

        Endpoint ini dipaginasi oleh backend Peatio (default 100 per
        halaman dari total ratusan pasar). Kita minta limit besar agar
        seluruh pasar ikut terbawa dalam satu request.
        """
        return self._request(
            "GET", "/public/markets", private=False, params={"limit": 1000}
        )

    def get_market_info(self, market_id: str) -> Dict[str, Any]:
        """
        Mencari metadata pasar spesifik (contoh: 'btcusdt') dari
        GET /public/markets.

        Raises:
            ValueError: jika market_id tidak ditemukan dalam daftar pasar.
        """
        markets = self.get_markets()
        market_id_lower = market_id.lower()

        for market in markets:
            candidate_id = str(market.get("id", market.get("name", ""))).lower()
            if candidate_id == market_id_lower:
                return market

        raise ValueError(f"Market '{market_id}' tidak ditemukan di SafeTrade.")

    # ------------------------------------------------------------------
    # Endpoint privat
    # ------------------------------------------------------------------
    def get_balances(self) -> List[Dict[str, Any]]:
        """
        GET /account/balances (Private)

        Mengembalikan daftar aset beserta currency dan balance (available).
        """
        return self._request("GET", "/account/balances", private=True)

    def get_balance_for(self, currency: str) -> Optional[Dict[str, Any]]:
        """Mengambil entri saldo untuk currency tertentu (case-insensitive)."""
        balances = self.get_balances()
        currency_lower = currency.lower()

        for entry in balances:
            if str(entry.get("currency", "")).lower() == currency_lower:
                return entry

        return None

    def get_order_book(self, market: str) -> Dict[str, Any]:
        """
        GET /public/markets/{market}/depth (Public)

        Mengembalikan order book (bids & asks) untuk market tertentu.
        Dipakai untuk mendapatkan harga bid terbaik sebagai nilai `price`
        pada order market sell (lihat catatan di create_market_sell_order).
        """
        return self._request(
            "GET", f"/public/markets/{market.lower()}/depth", private=False
        )

    def get_best_bid_price(self, market: str) -> Optional[str]:
        """Ambil harga bid tertinggi saat ini dari order book, atau None jika kosong."""
        depth = self.get_order_book(market)
        bids = depth.get("bids", [])
        if not bids:
            return None
        return str(bids[0][0])

    def create_market_sell_order(
        self, market: str, volume: str, price: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        POST /market/orders (Private)

        Membuat Market Sell Order.

        Catatan penting (ditemukan lewat trial-and-error terhadap API ini):
        meskipun `type="market"`, backend SafeTrade TETAP MEWAJIBKAN field
        `price` disertakan dalam payload agar lolos validasi skema
        (tanpa `price` -> error 'market.order.type_doesnt_exist').
        Nilai `price` ini hanya untuk lolos validasi; eksekusi order market
        tetap mengikuti harga bid terbaik yang berlaku di order book saat
        order matching terjadi, BUKAN nilai `price` yang dikirim di sini.
        Jika `price` tidak diberikan, akan diambil otomatis dari bid
        tertinggi saat ini (get_best_bid_price).

        Args:
            market: ID pasar huruf kecil (contoh: 'pearlusdt').
            volume: Jumlah koin yang akan dijual, dalam bentuk string
                    (hasil pembulatan Decimal) agar tidak kehilangan presisi.
            price: Harga acuan (lihat catatan di atas). Opsional.
        """
        if price is None:
            price = self.get_best_bid_price(market)
            if price is None:
                raise SafeTradeAPIError(
                    0, f"Order book kosong untuk market '{market}', tidak bisa menentukan price acuan."
                )

        # Catatan: field jumlah koin yang benar untuk API ini adalah
        # "amount" (BUKAN "volume" seperti istilah generik Peatio di
        # README). Terkonfirmasi lewat trial-and-error: payload dengan
        # "volume" selalu dianggap 0 oleh backend (error
        # 'non_positive_amount'), sedangkan "amount" dikenali dengan benar
        # (error 'amount_less_than_min_amount' saat nilainya di bawah
        # minimum pasar -- membuktikan field ini yang dibaca backend).
        payload = {
            "market": market.lower(),
            "side": "sell",
            "type": "market",
            "amount": str(volume),
            "price": str(price),
        }
        logger.debug("Mengirim order: %s", payload)
        return self._request("POST", "/market/orders", private=True, json_body=payload)
