"""
╔══════════════════════════════════════════════════════╗
║        MEMECOIN SNIPER BOT v3.0 - FULL AUTO          ║
║   DexScreener + Birdeye/Solscan + Telegram Alerts    ║
╚══════════════════════════════════════════════════════╝
"""

import requests
import time
import logging
import sys
import os

# ─────────────────────────────────────────────
#  CONFIG — Use env vars on Railway, or paste directly
# ─────────────────────────────────────────────

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "PASTE_YOUR_TELEGRAM_BOT_TOKEN")
CHAT_ID     = os.environ.get("CHAT_ID", "PASTE_YOUR_CHAT_ID")
BIRDEYE_KEY = os.environ.get("BIRDEYE_KEY", "")

WALLETS = [
    # Paste full Solana wallet addresses here
    # "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
]

# ─────────────────────────────────────────────
#  FILTERS
# ─────────────────────────────────────────────

MIN_SCORE           = 4
MAX_PAIR_AGE_MIN    = 120
MIN_LIQUIDITY       = 0       # 0 = skip liq filter (DexScreener often returns $0)
MIN_VOLUME_24H      = 500
MAX_MARKET_CAP      = 5_000_000
SCAN_INTERVAL_SEC   = 15
WALLET_CHECK_EVERY  = 3

SEARCH_QUERIES = [
    "sol", "pump", "moon", "pepe", "inu", "ai",
]

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("SniperBot")

# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────

seen_tokens    = set()
wallet_tx_seen = {}
stats = {
    "cycles"       : 0,
    "alerts_sent"  : 0,
    "pairs_scanned": 0,
    "start_time"   : time.time(),
}

# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────

def send_telegram(msg: str, silent: bool = False):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id"                : CHAT_ID,
            "text"                   : msg,
            "disable_notification"   : silent,
            "disable_web_page_preview": True,
        }
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code != 200:
            log.warning(f"Telegram error {r.status_code}: {r.text[:80]}")
    except Exception as e:
        log.error(f"Telegram failed: {e}")


def send_startup_message():
    msg = (
        "Memecoin Sniper Bot v3.0 Started\n\n"
        f"Min Score:    {MIN_SCORE}/13\n"
        f"Max Age:      {MAX_PAIR_AGE_MIN}m\n"
        f"Min Vol 24h:  ${MIN_VOLUME_24H:,}\n"
        f"Max MC:       ${MAX_MARKET_CAP:,}\n"
        f"Scan Every:   {SCAN_INTERVAL_SEC}s\n"
        f"Queries:      {len(SEARCH_QUERIES)}\n"
        f"Wallets:      {len(WALLETS)}\n\n"
        "Monitoring Solana pairs..."
    )
    send_telegram(msg)

# ─────────────────────────────────────────────
#  DEXSCREENER
# ─────────────────────────────────────────────

def fetch_new_pairs() -> list:
    all_pairs = []
    seen_addr = set()

    for query in SEARCH_QUERIES:
        try:
            url = f"https://api.dexscreener.com/latest/dex/search?q={query}"
            r   = requests.get(url, timeout=12)
            if r.status_code != 200:
                continue

            data  = r.json()
            pairs = data if isinstance(data, list) else data.get("pairs", []) or []

            for p in pairs:
                if not isinstance(p, dict):
                    continue
                if p.get("chainId", "") != "solana":
                    continue
                addr = p.get("pairAddress", "")
                if addr and addr not in seen_addr:
                    seen_addr.add(addr)
                    all_pairs.append(p)

        except Exception as e:
            log.error(f"DexScreener [{query}] error: {e}")
            continue

    now_ms  = int(time.time() * 1000)
    max_age = MAX_PAIR_AGE_MIN * 60 * 1000

    filtered = []
    for p in all_pairs:
        created = p.get("pairCreatedAt")
        if created:
            if (now_ms - int(created)) <= max_age:
                filtered.append(p)
        else:
            filtered.append(p)

    log.info(f"DexScreener: {len(all_pairs)} unique -> {len(filtered)} within {MAX_PAIR_AGE_MIN}m")
    stats["pairs_scanned"] += len(filtered)
    return filtered

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def safe_float(val, default=0.0) -> float:
    try:
        return float(val or default)
    except:
        return default

def get_liquidity(pair) -> float:
    liq = pair.get("liquidity", {})
    if isinstance(liq, dict):
        return safe_float(liq.get("usd", 0))
    return safe_float(liq)

def get_volume(pair, period="h24") -> float:
    vol = pair.get("volume", {})
    if isinstance(vol, dict):
        return safe_float(vol.get(period, 0))
    return 0.0

def get_price_change(pair, period="h1") -> float:
    pc = pair.get("priceChange", {})
    if isinstance(pc, dict):
        return safe_float(pc.get(period, 0))
    return 0.0

def get_txns(pair, period="h24") -> dict:
    return pair.get("txns", {}).get(period, {}) or {}

# ─────────────────────────────────────────────
#  FILTERS
# ─────────────────────────────────────────────

def passes_filters(pair) -> tuple:
    liq = get_liquidity(pair)
    vol = get_volume(pair, "h24")
    mc  = safe_float(pair.get("fdv"))

    if liq > 0 and MIN_LIQUIDITY > 0 and liq < MIN_LIQUIDITY:
        return False, f"Liq ${liq:.0f}"
    if vol < MIN_VOLUME_24H:
        return False, f"Vol ${vol:.0f}"
    if mc > MAX_MARKET_CAP and mc > 0:
        return False, f"MC too high"

    return True, ""

# ─────────────────────────────────────────────
#  SCORE ENGINE (max 13)
# ─────────────────────────────────────────────

def score_token(pair) -> tuple:
    score   = 0
    reasons = []

    try:
        mc    = safe_float(pair.get("fdv"))
        liq   = get_liquidity(pair)
        vol24 = get_volume(pair, "h24")
        vol1  = get_volume(pair, "h1")
        ch1   = get_price_change(pair, "h1")

        txns24 = get_txns(pair, "h24")
        buys   = safe_float(txns24.get("buys"))
        sells  = safe_float(txns24.get("sells"))

        txns5  = get_txns(pair, "m5")
        buys5  = safe_float(txns5.get("buys"))
        sells5 = safe_float(txns5.get("sells"))

        if liq >= 5_000:  score += 1; reasons.append("Liq>5k")
        if liq >= 20_000: score += 1; reasons.append("Liq>20k")
        if liq >= 50_000: score += 1; reasons.append("Liq>50k")

        if vol24 >= 10_000: score += 1; reasons.append("Vol>10k")
        if vol24 >= 50_000: score += 1; reasons.append("Vol>50k")

        if vol1 >= 5_000:  score += 1; reasons.append("Vol1h>5k")
        if vol1 >= 20_000: score += 1; reasons.append("Vol1h>20k")

        if sells > 0 and buys >= sells * 1.5:
            score += 2; reasons.append("BuyPressure")
        elif buys > sells:
            score += 1; reasons.append("MoreBuys")

        if buys5 > sells5 * 2 and buys5 >= 5:
            score += 1; reasons.append("5mSpike")

        if 0 < mc <= 500_000: score += 1; reasons.append("MC<500k")
        if 0 < mc <= 200_000: score += 1; reasons.append("MC<200k")

        if ch1 >= 20: score += 1; reasons.append(f"+{ch1:.0f}%1h")

    except Exception as e:
        log.warning(f"Score error: {e}")

    return score, reasons

# ─────────────────────────────────────────────
#  ALERT FORMATTER — Plain text, no HTML
# ─────────────────────────────────────────────

def format_alert(pair, score, reasons) -> str:
    name   = str(pair.get("baseToken", {}).get("name", "Unknown"))
    symbol = str(pair.get("baseToken", {}).get("symbol", "???"))
    addr   = pair.get("pairAddress", "")
    baddr  = pair.get("baseToken", {}).get("address", "")
    dex    = pair.get("dexId", "unknown").title()

    mc    = int(safe_float(pair.get("fdv")))
    liq   = int(get_liquidity(pair))
    vol24 = int(get_volume(pair, "h24"))
    vol1  = int(get_volume(pair, "h1"))
    ch1   = get_price_change(pair, "h1")
    ch24  = get_price_change(pair, "h24")

    txns  = get_txns(pair, "h24")
    buys  = int(safe_float(txns.get("buys")))
    sells = int(safe_float(txns.get("sells")))
    ratio = f"{buys/(sells+1):.1f}x"

    price = pair.get("priceUsd", "?")
    try:
        pf    = float(price)
        price = f"${pf:.8f}" if pf < 0.01 else f"${pf:.4f}"
    except:
        price = str(price)

    created = pair.get("pairCreatedAt")
    if created:
        age_sec = int(time.time()) - int(created) // 1000
        age_str = f"{age_sec // 60}m {age_sec % 60}s" if age_sec < 3600 else f"{age_sec // 3600}h {(age_sec % 3600) // 60}m"
    else:
        age_str = "Unknown"

    if score >= 9:   signal = "STRONG BUY"
    elif score >= 7: signal = "HIGH POTENTIAL"
    elif score >= 5: signal = "WATCH"
    else:            signal = "EARLY SIGNAL"

    emoji = "🚀" if score >= 9 else "🔥" if score >= 7 else "⚡" if score >= 5 else "👀"
    reasons_str = " | ".join(reasons) if reasons else "—"

    msg = (
        f"{emoji} {signal}\n"
        f"====================\n"
        f"🪙 {name} ({symbol})\n"
        f"🏦 DEX: {dex}\n\n"
        f"⭐ Score:    {score}/13\n"
        f"✅ {reasons_str}\n\n"
        f"💰 MC:       ${mc:,}\n"
        f"💧 Liq:      ${liq:,}\n"
        f"📊 Vol 24h:  ${vol24:,}\n"
        f"📊 Vol 1h:   ${vol1:,}\n"
        f"📈 1h/24h:   {ch1:+.1f}% / {ch24:+.1f}%\n"
        f"🟢 Buys: {buys}  🔴 Sells: {sells}  ({ratio})\n"
        f"💵 Price:    {price}\n"
        f"🕐 Age:      {age_str}\n\n"
        f"📊 Chart:\nhttps://dexscreener.com/solana/{addr}\n\n"
        f"🐦 Birdeye:\nhttps://birdeye.so/token/{baddr}?chain=solana"
    )
    return msg

# ─────────────────────────────────────────────
#  WALLET TRACKER
# ─────────────────────────────────────────────

def fetch_wallet_tx_birdeye(wallet: str) -> list:
    try:
        headers = {"X-API-KEY": BIRDEYE_KEY, "accept": "application/json"}
        r = requests.get(
            "https://public-api.birdeye.so/v1/wallet/tx_list",
            headers=headers,
            params={"wallet": wallet, "limit": 10},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        data = r.json().get("data", {})
        return data if isinstance(data, list) else data.get("transactions", [])
    except:
        return []


def fetch_wallet_tx_solscan(wallet: str) -> list:
    try:
        r = requests.get(
            "https://public-api.solscan.io/account/transactions",
            params={"account": wallet, "limit": 10},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return data if isinstance(data, list) else []
    except:
        return []


def fetch_wallet_tx(wallet: str) -> list:
    if BIRDEYE_KEY:
        txs = fetch_wallet_tx_birdeye(wallet)
        if txs:
            return txs
    return fetch_wallet_tx_solscan(wallet)


def track_wallets():
    if not WALLETS:
        return
    for wallet in WALLETS:
        try:
            txs = fetch_wallet_tx(wallet)
            if not txs:
                continue
            if wallet not in wallet_tx_seen:
                wallet_tx_seen[wallet] = set()
                for tx in txs:
                    tx_id = tx.get("txHash") or tx.get("signature", "")
                    if tx_id:
                        wallet_tx_seen[wallet].add(tx_id)
                log.info(f"Wallet seeded: {wallet[:8]}...")
                continue
            for tx in txs[:5]:
                tx_id = tx.get("txHash") or tx.get("signature", "")
                if not tx_id or tx_id in wallet_tx_seen[wallet]:
                    continue
                wallet_tx_seen[wallet].add(tx_id)
                token     = tx.get("symbol") or tx.get("tokenSymbol", "???")
                side      = tx.get("side") or tx.get("type", "unknown")
                value_usd = safe_float(tx.get("valueUsd") or tx.get("usdValue", 0))
                short     = f"{wallet[:6]}...{wallet[-4:]}"
                emoji     = "🟢" if "buy" in side.lower() else "🔴" if "sell" in side.lower() else "🔵"
                msg = (
                    f"🐋 WHALE WALLET MOVE\n"
                    f"====================\n"
                    f"Wallet: {short}\n"
                    f"{emoji} {side.upper()} -> {token}\n"
                    f"Value: ${value_usd:,.0f}\n"
                    f"TX: https://solscan.io/tx/{tx_id}"
                )
                send_telegram(msg)
        except Exception as e:
            log.error(f"Wallet error: {e}")

# ─────────────────────────────────────────────
#  STATS
# ─────────────────────────────────────────────

def report_stats():
    uptime = int(time.time() - stats["start_time"])
    h, m   = uptime // 3600, (uptime % 3600) // 60
    msg = (
        f"📊 Bot Stats\n"
        f"====================\n"
        f"Uptime:        {h}h {m}m\n"
        f"Cycles:        {stats['cycles']}\n"
        f"Pairs Scanned: {stats['pairs_scanned']}\n"
        f"Alerts Sent:   {stats['alerts_sent']}\n"
        f"Seen Tokens:   {len(seen_tokens)}"
    )
    send_telegram(msg, silent=True)

# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────

def main():
    log.info("=" * 54)
    log.info("   MEMECOIN SNIPER BOT v3.0 - STARTING")
    log.info("=" * 54)
    log.info(f"Min Score:   {MIN_SCORE}/13")
    log.info(f"Max Age:     {MAX_PAIR_AGE_MIN}m")
    log.info(f"Min Vol:     ${MIN_VOLUME_24H:,}")
    log.info(f"Max MC:      ${MAX_MARKET_CAP:,}")
    log.info(f"Queries:     {len(SEARCH_QUERIES)}")
    log.info(f"Wallets:     {len(WALLETS)}")
    log.info("=" * 54)

    send_startup_message()

    while True:
        try:
            stats["cycles"] += 1
            cycle = stats["cycles"]
            log.info(f"--- Cycle {cycle} ---")

            if cycle % WALLET_CHECK_EVERY == 1:
                track_wallets()

            if cycle % 100 == 0:
                report_stats()

            pairs = fetch_new_pairs()
            alerts_this_cycle = 0

            for pair in pairs:
                try:
                    addr = pair.get("pairAddress", "")
                    if not addr or addr in seen_tokens:
                        continue

                    passes, reason = passes_filters(pair)
                    if not passes:
                        continue

                    score, reasons = score_token(pair)
                    if score < MIN_SCORE:
                        continue

                    seen_tokens.add(addr)
                    msg = format_alert(pair, score, reasons)
                    sym = pair.get("baseToken", {}).get("symbol", "?")
                    log.info(f"ALERT [{score}/13] {sym} - {' | '.join(reasons)}")
                    send_telegram(msg)
                    stats["alerts_sent"] += 1
                    alerts_this_cycle += 1

                    if alerts_this_cycle > 1:
                        time.sleep(0.5)

                except Exception as e:
                    log.error(f"Pair error: {e}")
                    continue

            log.info(f"Alerts: {alerts_this_cycle} | Total: {stats['alerts_sent']} | Cache: {len(seen_tokens)}")

            if len(seen_tokens) > 3000:
                seen_tokens.clear()
                log.info("Cache cleared")

            time.sleep(SCAN_INTERVAL_SEC)

        except KeyboardInterrupt:
            log.info("Stopped.")
            send_telegram("Bot Stopped")
            break
        except Exception as e:
            log.error(f"Main loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
