"""
╔══════════════════════════════════════════════════════════╗
║       MEMECOIN PRO SNIPER BOT v4.2                       ║
║       DUAL MODE: Pump.fun Early + Raydium/Orca Strong    ║
║       QUALITY MODE — Strong Signals Only (3-5/hour)      ║
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
    # "E1zGzPY1WdJoHSzf928NWTkZjcAhnUaN1xzF6BhCTsvS"
      "J9TYAsWWidbrcZybmLSfrLzryANf4CgJBLdvwdGuC8MB"
      "ALJ4P5QNyHeLEjpKGmA1eUfJHSEGQMjY8HLnDkSgjczb"
      "91cJmU5pLnmSPuynUJkSz3WSGc8yzxMGoJ6RLz8ZeU4E"
      "4sgd7efDkAWuZWE9BYHLyXHuPu8V8DmvvZro45BN8mdm",
]

# ─────────────────────────────────────────────
#  PUMP.FUN FILTERS — Ultra early, high activity
# ─────────────────────────────────────────────

PUMP_MIN_SCORE      = 6        # High quality only
PUMP_MAX_AGE_MIN    = 60       # Only last 30 min (ultra fresh)
PUMP_MIN_VOLUME_24H = 10_000   # $10k volume
PUMP_MIN_VOLUME_1H  = 1_000    # $1k last hour — active token
PUMP_MIN_BUYS       = 20       # 20+ real buyers
PUMP_MIN_BUY_RATIO  = 1.3      # 1.3x more buys than sells
PUMP_MAX_MC         = 200_000  # Max $200k MC — true early

# ─────────────────────────────────────────────
#  REAL DEX FILTERS — Raydium / Orca / Meteora
# ─────────────────────────────────────────────

DEX_MIN_SCORE       = 6        # High quality only
DEX_MAX_AGE_MIN     = 120      # Last 2 hours
DEX_MIN_LIQUIDITY   = 30_000   # $30k real liquidity
DEX_MIN_VOLUME_24H  = 20_000   # $20k volume
DEX_MIN_VOLUME_1H   = 2_000    # $2k last hour
DEX_MIN_BUYS        = 20       # 20+ buyers
DEX_MIN_BUY_RATIO   = 1.5      # 1.5x buy ratio
DEX_MIN_MC          = 10_000   # Min $10k
DEX_MAX_MC          = 10_000_000  # Max $10M

# ─────────────────────────────────────────────
#  DEX CLASSIFICATION
# ─────────────────────────────────────────────

PUMP_DEXES = ["pump-fun", "pumpfun", "pump_fun", "pump"]
REAL_DEXES = ["raydium", "orca", "meteora", "jupiter", "lifinity"]

SCAN_INTERVAL_SEC  = 12
WALLET_CHECK_EVERY = 3

DEXSCREENER_QUERIES = [
    "raydium", "orca", "meteora",
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
    "alerts_pump"  : 0,
    "alerts_dex"   : 0,
    "pairs_scanned": 0,
    "rugs_skipped" : 0,
    "start_time"   : time.time(),
}

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

def get_dex_type(pair) -> str:
    dex = pair.get("dexId", "").lower()
    if any(p in dex for p in PUMP_DEXES):
        return "pump"
    if any(r in dex for r in REAL_DEXES):
        return "real"
    return "other"

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
        "PRO SNIPER v4.2 - QUALITY MODE\n"
        "================================\n\n"
        "PUMP.FUN (Ultra Early):\n"
        f"  Score:    {PUMP_MIN_SCORE}+/15\n"
        f"  Age:      <{PUMP_MAX_AGE_MIN}m\n"
        f"  Vol 1h:   ${PUMP_MIN_VOLUME_1H:,}+\n"
        f"  Buys:     {PUMP_MIN_BUYS}+\n"
        f"  Ratio:    {PUMP_MIN_BUY_RATIO}x+\n"
        f"  Max MC:   ${PUMP_MAX_MC:,}\n\n"
        "REAL DEX (Raydium/Orca):\n"
        f"  Score:    {DEX_MIN_SCORE}+/15\n"
        f"  Liq:      ${DEX_MIN_LIQUIDITY:,}+\n"
        f"  Vol 1h:   ${DEX_MIN_VOLUME_1H:,}+\n"
        f"  Buys:     {DEX_MIN_BUYS}+\n"
        f"  Ratio:    {DEX_MIN_BUY_RATIO}x+\n"
        f"  Max MC:   ${DEX_MAX_MC:,}\n\n"
        "Target: 3-5 strong alerts/hour\n"
        "Scanning ALL Solana DEXes..."
    )
    send_telegram(msg)

# ─────────────────────────────────────────────
#  DEXSCREENER
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

    log.info(f"DexScreener: {len(all_pairs)} unique Solana pairs")
    return all_pairs

# ─────────────────────────────────────────────
#  BIRDEYE
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
        r = requests.get(
            "https://public-api.birdeye.so/defi/v2/tokens/new_listing",
            headers=headers,
            params={"limit": 50},
            timeout=12,
        )
        if r.status_code != 200:
            return []
        tokens = r.json().get("data", {}).get("items", []) or []
        log.info(f"Birdeye: {len(tokens)} new tokens")
        return tokens
    except Exception as e:
        log.warning(f"Birdeye: {e}")
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
        return r.json().get("data", {}) or {} if r.status_code == 200 else {}
    except:
        return {}


def birdeye_to_pair(token: dict) -> dict:
    try:
        address = token.get("address", "")
        detail  = fetch_birdeye_token_detail(address)
        created = token.get("listingTime") or token.get("createdAt")
        return {
            "chainId"      : "solana",
            "pairAddress"  : address,
            "dexId"        : token.get("source", "birdeye"),
            "baseToken"    : {
                "address": address,
                "symbol" : token.get("symbol", "???"),
                "name"   : token.get("name", "Unknown"),
            },
            "fdv"          : safe_float(detail.get("mc", 0)),
            "priceUsd"     : str(safe_float(detail.get("price", 0))),
            "pairCreatedAt": int(created) * 1000 if created else None,
            "liquidity"    : {"usd": safe_float(detail.get("liquidity", 0))},
            "volume"       : {
                "h24": safe_float(detail.get("v24hUSD", 0)),
                "h1" : safe_float(detail.get("v1hUSD", 0)),
                "m5" : 0,
            },
            "txns": {
                "h24": {
                    "buys" : safe_float(detail.get("buy24h", 0)),
                    "sells": safe_float(detail.get("sell24h", 0)),
                },
                "m5": {"buys": 0, "sells": 0},
            },
            "priceChange": {
                "h1" : safe_float(detail.get("priceChange1hPercent", 0)),
                "h24": safe_float(detail.get("priceChange24hPercent", 0)),
            },
            "_source": "birdeye",
        }
    except Exception as e:
        log.warning(f"Birdeye convert: {e}")
        return {}


def fetch_all_pairs() -> list:
    dex_pairs      = fetch_dexscreener_pairs()
    birdeye_tokens = fetch_birdeye_new_tokens()
    existing       = {p.get("baseToken", {}).get("address", "") for p in dex_pairs}

    birdeye_pairs = []
    for token in birdeye_tokens:
        addr = token.get("address", "")
        if addr and addr not in existing:
            pair = birdeye_to_pair(token)
            if pair:
                birdeye_pairs.append(pair)
                existing.add(addr)

    all_pairs  = dex_pairs + birdeye_pairs
    now_ms     = int(time.time() * 1000)
    max_age_ms = max(PUMP_MAX_AGE_MIN, DEX_MAX_AGE_MIN) * 60 * 1000

    filtered = []
    for p in all_pairs:
        created = p.get("pairCreatedAt")
        if created:
            if (now_ms - int(created)) <= max_age_ms:
                filtered.append(p)
        else:
            filtered.append(p)

    stats["pairs_scanned"] += len(filtered)
    log.info(f"Total: {len(dex_pairs)} DEX + {len(birdeye_pairs)} Birdeye = {len(filtered)} in window")
    return filtered

# ─────────────────────────────────────────────
#  RUGCHECK
# ─────────────────────────────────────────────

def is_rug(token_address: str) -> bool:
    try:
        r = requests.get(
            f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report/summary",
            timeout=6,
        )
        if r.status_code != 200:
            return False
        data  = r.json()
        score = safe_float(data.get("score", 0))
        risks = [str(r.get("name", "")).lower() for r in data.get("risks", [])]
        bad   = ["freeze authority", "mint authority", "honeypot", "high tax"]
        if any(b in risk for b in bad for risk in risks):
            return True
        return score > 700
    except:
        return False

# ─────────────────────────────────────────────
#  DUAL FILTERS
# ─────────────────────────────────────────────

def passes_pump_filters(pair) -> tuple:
    vol24 = get_volume(pair, "h24")
    vol1  = get_volume(pair, "h1")
    mc    = safe_float(pair.get("fdv"))
    age   = get_pair_age_minutes(pair)
    txns  = get_txns(pair, "h24")
    buys  = safe_float(txns.get("buys", 0))
    sells = safe_float(txns.get("sells", 0))

    if age < 9999 and age > PUMP_MAX_AGE_MIN:
        return False, f"Age {age:.0f}m > {PUMP_MAX_AGE_MIN}m"
    if vol24 < PUMP_MIN_VOLUME_24H:
        return False, f"Vol24h ${vol24:.0f}"
    if vol1 < PUMP_MIN_VOLUME_1H:
        return False, f"Vol1h ${vol1:.0f}"
    if mc > PUMP_MAX_MC and mc > 0:
        return False, f"MC ${mc:,.0f}"
    if buys < PUMP_MIN_BUYS:
        return False, f"Buys {int(buys)} < {PUMP_MIN_BUYS}"
    if sells > 0 and buys / sells < PUMP_MIN_BUY_RATIO:
        return False, f"Ratio {buys/(sells+1):.1f}x"

    return True, ""


def passes_dex_filters(pair) -> tuple:
    liq   = get_liquidity(pair)
    vol24 = get_volume(pair, "h24")
    vol1  = get_volume(pair, "h1")
    mc    = safe_float(pair.get("fdv"))
    age   = get_pair_age_minutes(pair)
    txns  = get_txns(pair, "h24")
    buys  = safe_float(txns.get("buys", 0))
    sells = safe_float(txns.get("sells", 0))

    if age < 9999 and age > DEX_MAX_AGE_MIN:
        return False, f"Age {age:.0f}m"
    if liq < DEX_MIN_LIQUIDITY:
        return False, f"Liq ${liq:,.0f}"
    if vol24 < DEX_MIN_VOLUME_24H:
        return False, f"Vol24h ${vol24:.0f}"
    if vol1 < DEX_MIN_VOLUME_1H:
        return False, f"Vol1h ${vol1:.0f}"
    if mc > 0 and mc < DEX_MIN_MC:
        return False, f"MC too low"
    if mc > DEX_MAX_MC and mc > 0:
        return False, f"MC ${mc:,.0f}"
    if buys < DEX_MIN_BUYS:
        return False, f"Buys {int(buys)} < {DEX_MIN_BUYS}"
    if sells > 0 and buys / sells < DEX_MIN_BUY_RATIO:
        return False, f"Ratio {buys/(sells+1):.1f}x"

    return True, ""

# ─────────────────────────────────────────────
#  SCORE ENGINE (max 15)
# ─────────────────────────────────────────────

def score_token(pair, dex_type: str) -> tuple:
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

        # Liquidity (real DEX only)
        if dex_type == "real":
            if liq >= 50_000:  score += 1; reasons.append("Liq>50k")
            if liq >= 100_000: score += 1; reasons.append("Liq>100k")
            if liq >= 200_000: score += 1; reasons.append("Liq>200k")

        # Volume 24h
        if vol24 >= 20_000:  score += 1; reasons.append("Vol>20k")
        if vol24 >= 100_000: score += 1; reasons.append("Vol>100k")
        if vol24 >= 500_000: score += 1; reasons.append("Vol>500k")

        # Volume 1h momentum
        if vol1 >= 10_000: score += 1; reasons.append("Vol1h>10k")
        if vol1 >= 50_000: score += 1; reasons.append("Vol1h>50k")

        # Volume spike 5m
        if vol1 > 0 and vol5m > 0 and (vol5m / (vol1 / 12 + 1)) > 2:
            score += 2; reasons.append("VolSpike5m")
        elif buys5 > sells5 * 2 and buys5 >= 20:
            score += 1; reasons.append("5mBuySpike")

        # Buy pressure
        if sells > 0:
            ratio = buys / sells
            if ratio >= 4.0:   score += 3; reasons.append(f"Buys{ratio:.1f}x")
            elif ratio >= 2.5: score += 2; reasons.append(f"Buys{ratio:.1f}x")
            elif ratio >= 1.5: score += 1; reasons.append(f"Buys{ratio:.1f}x")

        # Market cap
        if 0 < mc <= 50_000:    score += 3; reasons.append("MC<50k")
        elif 0 < mc <= 100_000: score += 2; reasons.append("MC<100k")
        elif 0 < mc <= 300_000: score += 1; reasons.append("MC<300k")

        # Age bonus — ultra fresh
        if 0 < age <= 5:    score += 3; reasons.append("Age<5m")
        elif 0 < age <= 15: score += 2; reasons.append("Age<15m")
        elif 0 < age <= 30: score += 1; reasons.append("Age<30m")

        # Price momentum
        if ch1 >= 200:  score += 3; reasons.append(f"+{ch1:.0f}%")
        elif ch1 >= 100: score += 2; reasons.append(f"+{ch1:.0f}%")
        elif ch1 >= 50:  score += 1; reasons.append(f"+{ch1:.0f}%")

        # Real DEX bonus
        if dex_type == "real":
            score += 1; reasons.append("RealDEX")

    except Exception as e:
        log.warning(f"Score error: {e}")

    return score, reasons

# ─────────────────────────────────────────────
#  ALERT FORMATTER
# ─────────────────────────────────────────────

def format_alert(pair, score, reasons, dex_type: str) -> str:
    name   = str(pair.get("baseToken", {}).get("name", "Unknown"))[:30]
    symbol = str(pair.get("baseToken", {}).get("symbol", "???"))[:10]
    addr   = pair.get("pairAddress", "")
    baddr  = pair.get("baseToken", {}).get("address", "")
    dex    = pair.get("dexId", "unknown").title()

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

    if score >= 13:   emoji, signal = "💎", "MEGA GEM"
    elif score >= 11: emoji, signal = "🚀", "STRONG BUY"
    elif score >= 9:  emoji, signal = "🔥", "HIGH POTENTIAL"
    else:             emoji, signal = "⚡", "WATCH NOW"

    type_tag = "⚡ PUMP.FUN" if dex_type == "pump" else "🏦 REAL DEX"
    liq_line = "💧 Liq:      Bonding Curve" if dex_type == "pump" else f"💧 Liq:      ${liq:,}"
    reasons_str = " | ".join(reasons)

    msg = (
        f"{emoji} {signal}  [{type_tag}]\n"
        f"================================\n"
        f"🪙 {name} ({symbol})\n"
        f"🏦 DEX: {dex}\n\n"
        f"⭐ Score: {score}/15\n"
        f"✅ {reasons_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{liq_line}\n"
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
            headers = {
                "X-API-KEY": BIRDEYE_KEY,
                "accept"   : "application/json",
                "x-chain"  : "solana",
            }
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
        data = r.json()
        return data if isinstance(data, list) else []
    except:
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
    total  = stats["alerts_pump"] + stats["alerts_dex"]
    rate   = total / max(uptime / 3600, 0.1)
    msg = (
        f"📊 PRO SNIPER STATS\n"
        f"================================\n"
        f"Uptime:        {h}h {m}m\n"
        f"Cycles:        {stats['cycles']}\n"
        f"Pairs Scanned: {stats['pairs_scanned']}\n"
        f"Total Alerts:  {total} ({rate:.1f}/hr)\n"
        f"  Pump.fun:    {stats['alerts_pump']}\n"
        f"  Real DEX:    {stats['alerts_dex']}\n"
        f"Rugs Skipped:  {stats['rugs_skipped']}\n"
        f"Cache:         {len(seen_tokens)}"
    )
    send_telegram(msg, silent=True)

# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────

def main():
    log.info("=" * 56)
    log.info("   MEMECOIN PRO SNIPER BOT v4.2 - QUALITY MODE")
    log.info("=" * 56)
    log.info(f"PUMP: score>={PUMP_MIN_SCORE} | age<{PUMP_MAX_AGE_MIN}m | vol1h>${PUMP_MIN_VOLUME_1H:,} | buys>={PUMP_MIN_BUYS} | ratio>={PUMP_MIN_BUY_RATIO}x")
    log.info(f"DEX:  score>={DEX_MIN_SCORE} | liq>=${DEX_MIN_LIQUIDITY:,} | vol1h>${DEX_MIN_VOLUME_1H:,} | buys>={DEX_MIN_BUYS} | ratio>={DEX_MIN_BUY_RATIO}x")
    log.info(f"Birdeye: {'ON' if BIRDEYE_KEY else 'OFF'}")
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
                    addr     = pair.get("pairAddress", "")
                    baddr    = pair.get("baseToken", {}).get("address", "")
                    sym      = pair.get("baseToken", {}).get("symbol", "?")
                    dex_type = get_dex_type(pair)

                    if not addr or addr in seen_tokens:
                        continue

                    # Route to correct filter
                    if dex_type == "pump":
                        passes, reason = passes_pump_filters(pair)
                        min_score = PUMP_MIN_SCORE
                    elif dex_type == "real":
                        passes, reason = passes_dex_filters(pair)
                        min_score = DEX_MIN_SCORE
                    else:
                        passes, reason = passes_pump_filters(pair)
                        min_score = PUMP_MIN_SCORE

                    if not passes:
                        continue

                    # Rug check
                    if baddr and is_rug(baddr):
                        log.info(f"RUG SKIPPED: {sym}")
                        stats["rugs_skipped"] += 1
                        seen_tokens.add(addr)
                        continue

                    score, reasons = score_token(pair, dex_type)
                    if score < min_score:
                        continue

                    seen_tokens.add(addr)
                    msg = format_alert(pair, score, reasons, dex_type)
                    log.info(f"ALERT [{score}/15] [{dex_type.upper()}] {sym} | {' | '.join(reasons)}")

                    send_telegram(msg)

                    if dex_type == "pump":
                        stats["alerts_pump"] += 1
                    else:
                        stats["alerts_dex"] += 1

                    alerts_this_cycle += 1
                    if alerts_this_cycle > 1:
                        time.sleep(0.4)

                except Exception as e:
                    log.error(f"Pair error: {e}")
                    continue

            total = stats["alerts_pump"] + stats["alerts_dex"]
            log.info(
                f"Alerts: {alerts_this_cycle} | "
                f"Total: {total} | "
                f"Pump: {stats['alerts_pump']} | "
                f"DEX: {stats['alerts_dex']} | "
                f"Cache: {len(seen_tokens)}"
            )

            if len(seen_tokens) > 5000:
                seen_tokens.clear()
                log.info("Cache cleared")

            time.sleep(SCAN_INTERVAL_SEC)

        except KeyboardInterrupt:
            log.info("Stopped.")
            send_telegram("PRO SNIPER BOT v4.2 STOPPED")
            break
        except Exception as e:
            log.error(f"Main loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
