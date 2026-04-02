"""
╔══════════════════════════════════════════════════════════╗
║       MEMECOIN PRO SNIPER BOT v4.0                       ║
║       All Solana DEX + Birdeye + DexScreener             ║
║       Strong Liquidity + Volume Spike + Early Detection  ║
╚══════════════════════════════════════════════════════════╝
"""

import requests
import time
import logging
import sys
import os

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

BOT_TOKEN   = os.environ.get("BOT_TOKEN",   "PASTE_TELEGRAM_BOT_TOKEN")
CHAT_ID     = os.environ.get("CHAT_ID",     "PASTE_CHAT_ID")
BIRDEYE_KEY = os.environ.get("BIRDEYE_KEY", "")

WALLETS = [
    # "FULL_SOLANA_WALLET_ADDRESS",
]

# ─────────────────────────────────────────────
#  STRONG FILTERS
# ─────────────────────────────────────────────

MIN_SCORE           = 6
MAX_PAIR_AGE_MIN    = 120
MIN_LIQUIDITY       = 20_000      # $30k minimum
MIN_VOLUME_24H      = 10_000      # $10k volume
MIN_VOLUME_1H       = 2_000       # $2k last hour
MIN_BUYS            = 20          # at least 20 buy txns
MIN_BUY_SELL_RATIO  = 1.3         # more buyers than sellers
MAX_MARKET_CAP      = 10_000_000  # max $10M MC
MIN_MARKET_CAP      = 10_000      # min $10k MC
SCAN_INTERVAL_SEC   = 12
WALLET_CHECK_EVERY  = 3

# All Solana DEXes — broad coverage
DEXSCREENER_QUERIES = [
    "raydium", "orca", "meteora", "pumpfun",
    "pump", "sol", "solana", "meme",
    "moon", "pepe", "inu", "cat",
    "ai", "dog", "baby", "based",
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
log = logging.getLogger("ProSniper")

# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────

seen_tokens    = set()
wallet_tx_seen = {}
stats = {
    "cycles"       : 0,
    "alerts_sent"  : 0,
    "pairs_scanned": 0,
    "filtered_liq" : 0,
    "filtered_vol" : 0,
    "filtered_mc"  : 0,
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
            log.warning(f"Telegram {r.status_code}: {r.text[:60]}")
    except Exception as e:
        log.error(f"Telegram error: {e}")


def send_startup():
    msg = (
        "PRO SNIPER BOT v4.0 STARTED\n"
        "============================\n"
        f"Min Score:    {MIN_SCORE}/15\n"
        f"Min Liq:      ${MIN_LIQUIDITY:,}\n"
        f"Min Vol 24h:  ${MIN_VOLUME_24H:,}\n"
        f"Min Vol 1h:   ${MIN_VOLUME_1H:,}\n"
        f"Min Buys:     {MIN_BUYS}\n"
        f"Buy/Sell:     {MIN_BUY_SELL_RATIO}x min\n"
        f"Max Age:      {MAX_PAIR_AGE_MIN}m\n"
        f"Max MC:       ${MAX_MARKET_CAP:,}\n"
        f"DEX Queries:  {len(DEXSCREENER_QUERIES)}\n"
        f"Birdeye:      {'ON' if BIRDEYE_KEY else 'OFF'}\n"
        f"Wallets:      {len(WALLETS)}\n\n"
        "Scanning ALL Solana DEXes..."
    )
    send_telegram(msg)

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

def get_pair_age_minutes(pair) -> float:
    created = pair.get("pairCreatedAt")
    if not created:
        return 9999
    return (int(time.time() * 1000) - int(created)) / 60000

def format_age(minutes: float) -> str:
    if minutes >= 9999:
        return "Unknown"
    m = int(minutes)
    s = int((minutes - m) * 60)
    if m >= 60:
        return f"{m // 60}h {m % 60}m"
    return f"{m}m {s}s"

# ─────────────────────────────────────────────
#  DEXSCREENER — All DEX multi-query
# ─────────────────────────────────────────────

def fetch_dexscreener_pairs() -> list:
    all_pairs = []
    seen_addr = set()

    for query in DEXSCREENER_QUERIES:
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
            log.warning(f"DexScreener [{query}]: {e}")
            continue

    log.info(f"DexScreener: {len(all_pairs)} unique Solana pairs")
    return all_pairs

# ─────────────────────────────────────────────
#  BIRDEYE — New tokens feed
# ─────────────────────────────────────────────

def fetch_birdeye_new_tokens() -> list:
    if not BIRDEYE_KEY:
        return []
    try:
        headers = {
            "X-API-KEY": BIRDEYE_KEY,
            "accept"   : "application/json",
            "x-chain"  : "solana",
        }
        url = "https://public-api.birdeye.so/defi/v2/tokens/new_listing"
        r   = requests.get(url, headers=headers, params={"limit": 50}, timeout=12)
        if r.status_code != 200:
            return []
        tokens = r.json().get("data", {}).get("items", []) or []
        log.info(f"Birdeye: {len(tokens)} new tokens")
        return tokens
    except Exception as e:
        log.warning(f"Birdeye error: {e}")
        return []


def fetch_birdeye_token_detail(address: str) -> dict:
    if not BIRDEYE_KEY:
        return {}
    try:
        headers = {
            "X-API-KEY": BIRDEYE_KEY,
            "accept"   : "application/json",
            "x-chain"  : "solana",
        }
        r = requests.get(
            "https://public-api.birdeye.so/defi/token_overview",
            headers=headers,
            params={"address": address},
            timeout=10,
        )
        if r.status_code != 200:
            return {}
        return r.json().get("data", {}) or {}
    except:
        return {}


def birdeye_token_to_pair(token: dict) -> dict:
    try:
        address = token.get("address", "")
        symbol  = token.get("symbol", "???")
        name    = token.get("name", "Unknown")
        detail  = fetch_birdeye_token_detail(address)

        liq   = safe_float(detail.get("liquidity", 0))
        vol24 = safe_float(detail.get("v24hUSD", 0))
        vol1  = safe_float(detail.get("v1hUSD", 0))
        mc    = safe_float(detail.get("mc", 0))
        price = safe_float(detail.get("price", 0))
        buys  = safe_float(detail.get("buy24h", 0))
        sells = safe_float(detail.get("sell24h", 0))
        ch1   = safe_float(detail.get("priceChange1hPercent", 0))
        ch24  = safe_float(detail.get("priceChange24hPercent", 0))
        created = token.get("listingTime") or token.get("createdAt")

        return {
            "chainId"      : "solana",
            "pairAddress"  : address,
            "dexId"        : token.get("source", "birdeye"),
            "baseToken"    : {"address": address, "symbol": symbol, "name": name},
            "fdv"          : mc,
            "priceUsd"     : str(price),
            "pairCreatedAt": int(created) * 1000 if created else None,
            "liquidity"    : {"usd": liq},
            "volume"       : {"h24": vol24, "h1": vol1, "m5": 0},
            "txns"         : {"h24": {"buys": buys, "sells": sells}, "m5": {"buys": 0, "sells": 0}},
            "priceChange"  : {"h1": ch1, "h24": ch24},
            "_source"      : "birdeye",
        }
    except Exception as e:
        log.warning(f"Birdeye convert: {e}")
        return {}


def fetch_all_pairs() -> list:
    dex_pairs      = fetch_dexscreener_pairs()
    birdeye_tokens = fetch_birdeye_new_tokens()
    existing_addrs = {p.get("baseToken", {}).get("address", "") for p in dex_pairs}

    birdeye_pairs = []
    for token in birdeye_tokens:
        addr = token.get("address", "")
        if addr and addr not in existing_addrs:
            pair = birdeye_token_to_pair(token)
            if pair:
                birdeye_pairs.append(pair)
                existing_addrs.add(addr)

    all_pairs = dex_pairs + birdeye_pairs
    log.info(f"Total: {len(dex_pairs)} DexScreener + {len(birdeye_pairs)} Birdeye = {len(all_pairs)}")

    # Age filter
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

    stats["pairs_scanned"] += len(filtered)
    log.info(f"After age filter: {len(filtered)} pairs")
    return filtered

# ─────────────────────────────────────────────
#  RUGCHECK
# ─────────────────────────────────────────────

def is_rug(token_address: str) -> bool:
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report/summary"
        r   = requests.get(url, timeout=6)
        if r.status_code != 200:
            return False
        data  = r.json()
        score = safe_float(data.get("score", 0))
        risks = [r.get("name", "").lower() for r in data.get("risks", [])]
        bad   = ["freeze authority", "mint authority", "honeypot", "high tax"]
        if any(b in risk for b in bad for risk in risks):
            return True
        return score > 700
    except:
        return False

# ─────────────────────────────────────────────
#  HARD FILTERS
# ─────────────────────────────────────────────

def passes_filters(pair) -> tuple:
    liq   = get_liquidity(pair)
    vol24 = get_volume(pair, "h24")
    vol1  = get_volume(pair, "h1")
    mc    = safe_float(pair.get("fdv"))
    txns  = get_txns(pair, "h24")
    buys  = safe_float(txns.get("buys", 0))
    sells = safe_float(txns.get("sells", 0))

    if liq > 0 and liq < MIN_LIQUIDITY:
        stats["filtered_liq"] += 1
        return False, f"Liq ${liq:,.0f} < ${MIN_LIQUIDITY:,}"

    if vol24 < MIN_VOLUME_24H:
        stats["filtered_vol"] += 1
        return False, f"Vol24h ${vol24:.0f}"

    if vol1 < MIN_VOLUME_1H:
        stats["filtered_vol"] += 1
        return False, f"Vol1h ${vol1:.0f}"

    if mc > 0 and mc < MIN_MARKET_CAP:
        stats["filtered_mc"] += 1
        return False, f"MC too low"

    if mc > MAX_MARKET_CAP and mc > 0:
        stats["filtered_mc"] += 1
        return False, f"MC too high"

    if buys < MIN_BUYS:
        return False, f"Only {int(buys)} buys"

    if sells > 0 and buys / sells < MIN_BUY_SELL_RATIO:
        return False, f"Ratio {buys/(sells+1):.1f}x"

    return True, ""

# ─────────────────────────────────────────────
#  SCORE ENGINE (max 15)
# ─────────────────────────────────────────────

def score_token(pair) -> tuple:
    score   = 0
    reasons = []

    try:
        mc    = safe_float(pair.get("fdv"))
        liq   = get_liquidity(pair)
        vol24 = get_volume(pair, "h24")
        vol1  = get_volume(pair, "h1")
        vol5m = get_volume(pair, "m5")
        ch1   = get_price_change(pair, "h1")
        age   = get_pair_age_minutes(pair)

        txns24 = get_txns(pair, "h24")
        buys   = safe_float(txns24.get("buys", 0))
        sells  = safe_float(txns24.get("sells", 0))
        txns5  = get_txns(pair, "m5")
        buys5  = safe_float(txns5.get("buys", 0))
        sells5 = safe_float(txns5.get("sells", 0))

        # Liquidity tiers
        if liq >= 30_000:  score += 1; reasons.append("Liq>30k")
        if liq >= 75_000:  score += 1; reasons.append("Liq>75k")
        if liq >= 150_000: score += 1; reasons.append("Liq>150k")

        # Volume 24h
        if vol24 >= 30_000:  score += 1; reasons.append("Vol>30k")
        if vol24 >= 100_000: score += 1; reasons.append("Vol>100k")
        if vol24 >= 300_000: score += 1; reasons.append("Vol>300k")

        # Volume 1h momentum
        if vol1 >= 10_000: score += 1; reasons.append("Vol1h>10k")
        if vol1 >= 50_000: score += 1; reasons.append("Vol1h>50k")

        # Volume spike 5m
        if vol1 > 0 and vol5m > 0 and (vol5m / (vol1 / 12)) > 2:
            score += 2; reasons.append("VolSpike5m")
        elif buys5 > sells5 * 2 and buys5 >= 10:
            score += 1; reasons.append("5mBuySpike")

        # Buy pressure
        if sells > 0:
            ratio = buys / sells
            if ratio >= 3.0:   score += 3; reasons.append(f"Buys{ratio:.1f}x")
            elif ratio >= 2.0: score += 2; reasons.append(f"Buys{ratio:.1f}x")
            elif ratio >= 1.5: score += 1; reasons.append(f"Buys{ratio:.1f}x")

        # Market cap
        if 0 < mc <= 100_000:   score += 2; reasons.append("MC<100k")
        elif 0 < mc <= 300_000: score += 1; reasons.append("MC<300k")
        elif 0 < mc <= 500_000: score += 1; reasons.append("MC<500k")

        # Age bonus
        if 0 < age <= 15:   score += 2; reasons.append("Age<15m")
        elif 0 < age <= 30: score += 1; reasons.append("Age<30m")

        # Price momentum
        if ch1 >= 50:   score += 2; reasons.append(f"+{ch1:.0f}%")
        elif ch1 >= 20: score += 1; reasons.append(f"+{ch1:.0f}%")

        # DEX bonus (non-pump = more legit)
        dex = pair.get("dexId", "")
        if dex in ["raydium", "orca", "meteora"]:
            score += 1; reasons.append(dex.title())

    except Exception as e:
        log.warning(f"Score error: {e}")

    return score, reasons

# ─────────────────────────────────────────────
#  ALERT FORMATTER
# ─────────────────────────────────────────────

def format_alert(pair, score, reasons) -> str:
    name   = str(pair.get("baseToken", {}).get("name", "Unknown"))[:30]
    symbol = str(pair.get("baseToken", {}).get("symbol", "???"))[:10]
    addr   = pair.get("pairAddress", "")
    baddr  = pair.get("baseToken", {}).get("address", "")
    dex    = pair.get("dexId", "unknown").title()
    source = pair.get("_source", "")

    mc    = int(safe_float(pair.get("fdv")))
    liq   = int(get_liquidity(pair))
    vol24 = int(get_volume(pair, "h24"))
    vol1  = int(get_volume(pair, "h1"))
    vol5m = int(get_volume(pair, "m5"))
    ch1   = get_price_change(pair, "h1")
    ch24  = get_price_change(pair, "h24")

    txns  = get_txns(pair, "h24")
    buys  = int(safe_float(txns.get("buys", 0)))
    sells = int(safe_float(txns.get("sells", 0)))
    ratio = f"{buys/(sells+1):.1f}x"

    txns5  = get_txns(pair, "m5")
    buys5  = int(safe_float(txns5.get("buys", 0)))
    sells5 = int(safe_float(txns5.get("sells", 0)))

    price = pair.get("priceUsd", "0")
    try:
        pf    = float(price)
        price = f"${pf:.10f}".rstrip("0") if pf < 0.001 else f"${pf:.6f}"
    except:
        price = str(price)

    age_str = format_age(get_pair_age_minutes(pair))
    src_tag = " [Birdeye]" if source == "birdeye" else ""

    if score >= 12:  emoji, signal = "💎", "MEGA GEM"
    elif score >= 10: emoji, signal = "🚀", "STRONG BUY"
    elif score >= 8:  emoji, signal = "🔥", "HIGH POTENTIAL"
    else:             emoji, signal = "⚡", "WATCH NOW"

    reasons_str = " | ".join(reasons)

    msg = (
        f"{emoji} {signal}{src_tag}\n"
        f"================================\n"
        f"🪙 {name} ({symbol})\n"
        f"🏦 DEX: {dex}\n\n"
        f"⭐ Score: {score}/15\n"
        f"✅ {reasons_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💧 Liq:      ${liq:,}\n"
        f"💰 MC:       ${mc:,}\n"
        f"📊 Vol 24h:  ${vol24:,}\n"
        f"📊 Vol 1h:   ${vol1:,}\n"
        f"📊 Vol 5m:   ${vol5m:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Buys 24h: {buys}  🔴 Sells: {sells}\n"
        f"⚖️  Ratio:   {ratio}\n"
        f"🟢 Buys 5m:  {buys5}  🔴 Sells: {sells5}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 1h:   {ch1:+.1f}%\n"
        f"📈 24h:  {ch24:+.1f}%\n"
        f"💵 Price: {price}\n"
        f"🕐 Age:   {age_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 https://dexscreener.com/solana/{addr}\n"
        f"🐦 https://birdeye.so/token/{baddr}?chain=solana\n"
        f"🔍 https://solscan.io/token/{baddr}"
    )
    return msg

# ─────────────────────────────────────────────
#  WALLET TRACKER
# ─────────────────────────────────────────────

def fetch_wallet_tx(wallet: str) -> list:
    if BIRDEYE_KEY:
        try:
            headers = {"X-API-KEY": BIRDEYE_KEY, "accept": "application/json", "x-chain": "solana"}
            r = requests.get(
                "https://public-api.birdeye.so/v1/wallet/tx_list",
                headers=headers,
                params={"wallet": wallet, "limit": 10},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                txs  = data if isinstance(data, list) else data.get("transactions", [])
                if txs:
                    return txs
        except:
            pass
    try:
        r = requests.get(
            "https://public-api.solscan.io/account/transactions",
            params={"account": wallet, "limit": 10},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
    except:
        pass
    return []


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
                emoji     = "🟢" if "buy" in side.lower() else "🔴"
                msg = (
                    f"🐋 WHALE MOVE\n"
                    f"================================\n"
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
        f"📊 PRO SNIPER STATS\n"
        f"================================\n"
        f"Uptime:        {h}h {m}m\n"
        f"Cycles:        {stats['cycles']}\n"
        f"Pairs Scanned: {stats['pairs_scanned']}\n"
        f"Alerts Sent:   {stats['alerts_sent']}\n"
        f"Seen Tokens:   {len(seen_tokens)}\n\n"
        f"Filtered:\n"
        f"Low Liq:  {stats['filtered_liq']}\n"
        f"Low Vol:  {stats['filtered_vol']}\n"
        f"Bad MC:   {stats['filtered_mc']}"
    )
    send_telegram(msg, silent=True)

# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────

def main():
    log.info("=" * 56)
    log.info("   MEMECOIN PRO SNIPER BOT v4.0 - STARTING")
    log.info("=" * 56)
    log.info(f"Min Score:   {MIN_SCORE}/15")
    log.info(f"Min Liq:     ${MIN_LIQUIDITY:,}")
    log.info(f"Min Vol 24h: ${MIN_VOLUME_24H:,}")
    log.info(f"Min Vol 1h:  ${MIN_VOLUME_1H:,}")
    log.info(f"Min Buys:    {MIN_BUYS}")
    log.info(f"Max Age:     {MAX_PAIR_AGE_MIN}m")
    log.info(f"DEX Queries: {len(DEXSCREENER_QUERIES)}")
    log.info(f"Birdeye:     {'ON' if BIRDEYE_KEY else 'OFF'}")
    log.info("=" * 56)

    send_startup()

    while True:
        try:
            stats["cycles"] += 1
            cycle = stats["cycles"]
            log.info(f"=== Cycle {cycle} ===")

            if cycle % WALLET_CHECK_EVERY == 1:
                track_wallets()

            if cycle % 100 == 0:
                report_stats()

            pairs = fetch_all_pairs()
            alerts_this_cycle = 0

            for pair in pairs:
                try:
                    addr  = pair.get("pairAddress", "")
                    baddr = pair.get("baseToken", {}).get("address", "")

                    if not addr or addr in seen_tokens:
                        continue

                    passes, reason = passes_filters(pair)
                    if not passes:
                        continue

                    # Rug check
                    if baddr and is_rug(baddr):
                        sym = pair.get("baseToken", {}).get("symbol", "?")
                        log.info(f"RUG SKIPPED: {sym}")
                        seen_tokens.add(addr)
                        continue

                    score, reasons = score_token(pair)
                    if score < MIN_SCORE:
                        continue

                    seen_tokens.add(addr)
                    msg = format_alert(pair, score, reasons)
                    sym = pair.get("baseToken", {}).get("symbol", "?")
                    log.info(f"ALERT [{score}/15] {sym} | {' | '.join(reasons)}")

                    send_telegram(msg)
                    stats["alerts_sent"] += 1
                    alerts_this_cycle += 1

                    if alerts_this_cycle > 1:
                        time.sleep(0.4)

                except Exception as e:
                    log.error(f"Pair error: {e}")
                    continue

            log.info(
                f"Alerts: {alerts_this_cycle} | "
                f"Total: {stats['alerts_sent']} | "
                f"Cache: {len(seen_tokens)}"
            )

            if len(seen_tokens) > 5000:
                seen_tokens.clear()
                log.info("Cache cleared")

            time.sleep(SCAN_INTERVAL_SEC)

        except KeyboardInterrupt:
            log.info("Stopped.")
            send_telegram("PRO SNIPER BOT STOPPED")
            break
        except Exception as e:
            log.error(f"Main loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
