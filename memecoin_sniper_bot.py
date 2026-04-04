"""
╔══════════════════════════════════════════════════════════╗
║       MEMECOIN PRO SNIPER BOT v4.4                       ║
║       THREE MODE DETECTION SYSTEM                        ║
║                                                          ║
║  MODE 1 — PUMP.FUN   : Ultra early gems <60m            ║
║  MODE 2 — REAL DEX   : Raydium/Orca new pairs           ║
║  MODE 3 — MOMENTUM   : Big coins $500k+ sudden spike    ║
║                                                          ║
║  RISK ENGINE: SAFE / RISKY / GAMBLE (GAMBLE filtered)   ║
║  WHALE CONCENTRATION DETECTION                          ║
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

# ─────────────────────────────────────────────
#  WHALE WALLETS
# ─────────────────────────────────────────────

WALLETS = [
    "E1zGzPY1WdJoHSzf928NWTkZjcAhnUaN1xzF6BhCTsvS",
    "J9TYAsWWidbrcZybmLSfrLzryANf4CgJBLdvwdGuC8MB",
    "ALJ4P5QNyHeLEjpKGmA1eUfJHSEGQMjY8HLnDkSgjczb",
    "91cJmU5pLnmSPuynUJkSz3WSGc8yzxMGoJ6RLz8ZeU4E",
    "4sgd7efDkAWuZWE9BYHLyXHuPu8V8DmvvZro45BN8mdm",
]

# ─────────────────────────────────────────────
#  MODE 1 — PUMP.FUN FILTERS
#  Ultra early gems on bonding curve
# ─────────────────────────────────────────────

PUMP_MIN_SCORE      = 5
PUMP_MAX_AGE_MIN    = 120
PUMP_MIN_VOLUME_24H = 1_000
PUMP_MIN_VOLUME_1H  = 500
PUMP_MIN_BUYS       = 10
PUMP_MIN_BUY_RATIO  = 1.2
PUMP_MAX_MC         = 1_000_000

# ─────────────────────────────────────────────
#  MODE 2 — REAL DEX FILTERS
#  New pairs on Raydium / Orca / Meteora
# ─────────────────────────────────────────────

DEX_MIN_SCORE       = 5
DEX_MAX_AGE_MIN     = 240
DEX_MIN_LIQUIDITY   = 5_000
DEX_MIN_VOLUME_24H  = 2_000
DEX_MIN_VOLUME_1H   = 500
DEX_MIN_BUYS        = 10
DEX_MIN_BUY_RATIO   = 1.2
DEX_MIN_MC          = 1_000
DEX_MAX_MC          = 50_000_000

# ─────────────────────────────────────────────
#  MODE 3 — MOMENTUM FILTERS
#  Established coins with sudden volume spike
#  $500k+ MC, $50k+ liquidity, activity surge
# ─────────────────────────────────────────────

MOM_MIN_SCORE         = 6
MOM_MIN_MC            = 500_000      # At least $500k MC
MOM_MAX_MC            = 50_000_000   # Max $50M (not mega cap)
MOM_MIN_LIQUIDITY     = 50_000       # Real liquidity $50k+
MOM_MIN_VOLUME_1H     = 20_000       # $20k in last hour
MOM_MIN_VOLUME_5M     = 5_000        # $5k in last 5 min (spike)
MOM_MIN_BUYS          = 50           # Active — 50+ buyers
MOM_MIN_BUY_RATIO     = 1.3          # More buys than sells
MOM_VOL_SPIKE_RATIO   = 3.0          # 5m vol must be 3x normal rate
MOM_MIN_PRICE_CHANGE  = 5.0          # At least +5% in 1h

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
    "cycles"        : 0,
    "alerts_pump"   : 0,
    "alerts_dex"    : 0,
    "alerts_momentum": 0,
    "pairs_scanned" : 0,
    "rugs_skipped"  : 0,
    "gamble_skipped": 0,
    "safe_count"    : 0,
    "risky_count"   : 0,
    "start_time"    : time.time(),
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

def get_vol_spike_ratio(pair) -> float:
    """How much faster is 5m volume vs normal 5m rate from 1h."""
    vol1  = get_volume(pair, "h1")
    vol5m = get_volume(pair, "m5")
    if vol1 <= 0:
        return 0.0
    normal_5m = vol1 / 12  # expected 5m vol based on 1h rate
    if normal_5m <= 0:
        return 0.0
    return vol5m / normal_5m

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
    wallets_short = [f"{w[:6]}...{w[-4:]}" for w in WALLETS]
    msg = (
        "PRO SNIPER v4.4 - THREE MODE\n"
        "================================\n\n"
        "MODE 1 - PUMP.FUN (Ultra Early):\n"
        f"  Score {PUMP_MIN_SCORE}+ | Age <{PUMP_MAX_AGE_MIN}m\n"
        f"  Vol1h ${PUMP_MIN_VOLUME_1H:,}+ | Buys {PUMP_MIN_BUYS}+\n"
        f"  MC <${PUMP_MAX_MC:,}\n\n"
        "MODE 2 - REAL DEX (New Pairs):\n"
        f"  Score {DEX_MIN_SCORE}+ | Liq ${DEX_MIN_LIQUIDITY:,}+\n"
        f"  Vol1h ${DEX_MIN_VOLUME_1H:,}+ | Buys {DEX_MIN_BUYS}+\n\n"
        "MODE 3 - MOMENTUM (Big Coins):\n"
        f"  Score {MOM_MIN_SCORE}+ | MC ${MOM_MIN_MC:,}+\n"
        f"  Liq ${MOM_MIN_LIQUIDITY:,}+ | Vol1h ${MOM_MIN_VOLUME_1H:,}+\n"
        f"  Vol5m ${MOM_MIN_VOLUME_5M:,}+ | Spike {MOM_VOL_SPIKE_RATIO}x+\n"
        f"  Buys {MOM_MIN_BUYS}+ | 1h change +{MOM_MIN_PRICE_CHANGE}%+\n\n"
        "GAMBLE signals: AUTO FILTERED\n"
        "RISK TAGS: SAFE / RISKY only\n\n"
        f"Wallets tracked: {len(WALLETS)}\n"
        + "\n".join(wallets_short) + "\n\n"
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

    all_pairs = dex_pairs + birdeye_pairs
    stats["pairs_scanned"] += len(all_pairs)
    log.info(f"Total: {len(dex_pairs)} DEX + {len(birdeye_pairs)} Birdeye = {len(all_pairs)}")
    return all_pairs

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
        risks = [str(x.get("name", "")).lower() for x in data.get("risks", [])]
        bad   = ["freeze authority", "mint authority", "honeypot", "high tax"]
        if any(b in risk for b in bad for risk in risks):
            return True
        return score > 700
    except:
        return False

# ─────────────────────────────────────────────
#  WHALE CONCENTRATION
# ─────────────────────────────────────────────

def check_whale_concentration(token_address: str) -> dict:
    if not BIRDEYE_KEY:
        return {}
    try:
        headers = {
            "X-API-KEY": BIRDEYE_KEY,
            "accept"   : "application/json",
            "x-chain"  : "solana",
        }
        r = requests.get(
            "https://public-api.birdeye.so/defi/token_holder",
            headers=headers,
            params={"address": token_address, "limit": 10},
            timeout=8,
        )
        if r.status_code != 200:
            return {}
        holders = r.json().get("data", {}).get("items", []) or []
        if not holders:
            return {}
        top1  = safe_float(holders[0].get("percentage", 0)) if len(holders) > 0 else 0
        top3  = sum(safe_float(h.get("percentage", 0)) for h in holders[:3])
        top5  = sum(safe_float(h.get("percentage", 0)) for h in holders[:5])
        top10 = sum(safe_float(h.get("percentage", 0)) for h in holders[:10])
        return {
            "top1" : round(top1, 1),
            "top3" : round(top3, 1),
            "top5" : round(top5, 1),
            "top10": round(top10, 1),
        }
    except:
        return {}

# ─────────────────────────────────────────────
#  RISK ENGINE
# ─────────────────────────────────────────────

def assess_risk(pair, dex_type: str, mode: str, score: int, holders: dict) -> tuple:
    mc     = safe_float(pair.get("fdv"))
    liq    = get_liquidity(pair)
    age    = get_pair_age_minutes(pair)
    vol24  = get_volume(pair, "h24")
    vol5m  = get_volume(pair, "m5")

    txns24 = get_txns(pair, "h24")
    buys   = safe_float(txns24.get("buys", 0))
    sells  = safe_float(txns24.get("sells", 0))
    txns5  = get_txns(pair, "m5")
    buys5  = safe_float(txns5.get("buys", 0))

    risk_pts = 0
    reasons  = []

    # Whale concentration
    if holders:
        top1 = holders.get("top1", 0)
        top5 = holders.get("top5", 0)
        if top1 > 30:
            risk_pts += 3; reasons.append(f"Top1={top1}%")
        elif top1 > 15:
            risk_pts += 2; reasons.append(f"Top1={top1}%")
        elif top1 > 8:
            risk_pts += 1; reasons.append(f"Top1={top1}%")
        if top5 > 60:
            risk_pts += 2; reasons.append(f"Top5={top5}%")
        elif top5 > 40:
            risk_pts += 1; reasons.append(f"Top5={top5}%")

    # Sudden dump risk (5m vol spike)
    if vol24 > 0 and vol5m / (vol24 + 1) > 0.6:
        risk_pts += 2; reasons.append("Vol spike >60% in 5m")
    elif vol24 > 0 and vol5m / (vol24 + 1) > 0.4:
        risk_pts += 1; reasons.append("Vol spike 40%+")

    # Buy concentration
    if buys > 0 and buys5 / (buys + 1) > 0.5:
        risk_pts += 2; reasons.append("Buy concentration")

    # Age risk (pump/dex only — momentum tokens are established)
    if mode != "momentum":
        if age < 5:
            risk_pts += 2; reasons.append("Age <5m")
        elif age < 15:
            risk_pts += 1; reasons.append("Age <15m")

    # MC risk
    if mode == "momentum":
        # Momentum tokens are established — MC is a positive signal
        if mc >= 1_000_000:
            risk_pts -= 1  # $1M+ MC = more stable
    else:
        if 0 < mc < 10_000:
            risk_pts += 3; reasons.append("MC <$10k")
        elif 0 < mc < 30_000:
            risk_pts += 2; reasons.append("MC <$30k")
        elif 0 < mc < 100_000:
            risk_pts += 1; reasons.append("MC <$100k")

    # Liquidity risk
    if mode == "momentum":
        if liq >= 100_000:
            risk_pts -= 1; reasons.append("Strong liq")
        elif liq < 50_000:
            risk_pts += 1; reasons.append("Liq <$50k")
    elif dex_type == "pump":
        risk_pts += 1; reasons.append("Bonding curve")
    elif liq < 20_000:
        risk_pts += 2; reasons.append("Liq <$20k")
    elif liq < 50_000:
        risk_pts += 1; reasons.append("Liq <$50k")

    # Sell pressure
    if sells > 0 and buys / (sells + 1) < 1.2:
        risk_pts += 1; reasons.append("Weak ratio")

    # Score bonus
    if score >= 12:
        risk_pts -= 2
    elif score >= 10:
        risk_pts -= 1

    # Real DEX with good liq = safer
    if dex_type == "real" and liq >= 50_000:
        risk_pts -= 1

    risk_pts = max(0, risk_pts)

    if risk_pts <= 2:
        tag   = "SAFE"
        emoji = "🟢"
    elif risk_pts <= 4:
        tag   = "RISKY"
        emoji = "🟡"
    else:
        tag   = "GAMBLE"
        emoji = "🔴"

    reason_str = " | ".join(reasons) if reasons else "No major risks"
    return tag, emoji, reason_str, risk_pts

# ─────────────────────────────────────────────
#  THREE FILTER MODES
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
        return False, f"Age {age:.0f}m"
    if vol24 < PUMP_MIN_VOLUME_24H:
        return False, f"Vol24h ${vol24:.0f}"
    if vol1 < PUMP_MIN_VOLUME_1H:
        return False, f"Vol1h ${vol1:.0f}"
    if mc > PUMP_MAX_MC and mc > 0:
        return False, f"MC ${mc:,.0f}"
    if buys < PUMP_MIN_BUYS:
        return False, f"Buys {int(buys)}"
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
        return False, f"Buys {int(buys)}"
    if sells > 0 and buys / sells < DEX_MIN_BUY_RATIO:
        return False, f"Ratio {buys/(sells+1):.1f}x"
    return True, ""


def passes_momentum_filters(pair) -> tuple:
    """
    Mode 3 — Big established coins with sudden activity surge.
    Detects when a $500k+ MC token suddenly gets volume spike.
    """
    mc      = safe_float(pair.get("fdv"))
    liq     = get_liquidity(pair)
    vol1    = get_volume(pair, "h1")
    vol5m   = get_volume(pair, "m5")
    ch1     = get_price_change(pair, "h1")
    txns24  = get_txns(pair, "h24")
    txns5   = get_txns(pair, "m5")
    buys    = safe_float(txns24.get("buys", 0))
    sells   = safe_float(txns24.get("sells", 0))
    buys5   = safe_float(txns5.get("buys", 0))
    sells5  = safe_float(txns5.get("sells", 0))
    spike   = get_vol_spike_ratio(pair)

    # MC must be established
    if mc < MOM_MIN_MC:
        return False, f"MC ${mc:,.0f} < ${MOM_MIN_MC:,}"
    if mc > MOM_MAX_MC:
        return False, f"MC too large"

    # Must have real liquidity
    if liq < MOM_MIN_LIQUIDITY:
        return False, f"Liq ${liq:,.0f} < ${MOM_MIN_LIQUIDITY:,}"

    # Must have 1h volume activity
    if vol1 < MOM_MIN_VOLUME_1H:
        return False, f"Vol1h ${vol1:.0f}"

    # Must have 5m spike
    if vol5m < MOM_MIN_VOLUME_5M:
        return False, f"Vol5m ${vol5m:.0f}"

    # Volume spike ratio check — 5m must be 3x normal rate
    if spike < MOM_VOL_SPIKE_RATIO:
        return False, f"Spike {spike:.1f}x < {MOM_VOL_SPIKE_RATIO}x"

    # Must have active buyers
    if buys < MOM_MIN_BUYS:
        return False, f"Buys {int(buys)}"

    # Buy pressure
    if sells > 0 and buys / sells < MOM_MIN_BUY_RATIO:
        return False, f"Ratio {buys/(sells+1):.1f}x"

    # Must be moving up
    if ch1 < MOM_MIN_PRICE_CHANGE:
        return False, f"1h change {ch1:+.1f}%"

    # 5m buy activity check
    if buys5 < 10:
        return False, f"5m buys {int(buys5)}"

    return True, ""


def detect_mode(pair) -> str:
    """
    Determine which mode to use for this pair.
    Momentum mode checked FIRST if MC is high enough.
    """
    mc      = safe_float(pair.get("fdv"))
    liq     = get_liquidity(pair)
    dex     = get_dex_type(pair)
    vol5m   = get_volume(pair, "m5")
    spike   = get_vol_spike_ratio(pair)

    # If MC > $500k AND liq > $50k AND volume spike — try momentum mode
    if mc >= MOM_MIN_MC and liq >= MOM_MIN_LIQUIDITY and spike >= MOM_VOL_SPIKE_RATIO:
        return "momentum"

    # Pump.fun early gem
    if dex == "pump":
        return "pump"

    # Real DEX new pair
    if dex == "real":
        return "real"

    # Unknown DEX — try pump filters
    return "pump"

# ─────────────────────────────────────────────
#  SCORE ENGINE (max 15)
# ─────────────────────────────────────────────

def score_token(pair, dex_type: str, mode: str) -> tuple:
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
        spike = get_vol_spike_ratio(pair)

        txns24 = get_txns(pair, "h24")
        buys   = safe_float(txns24.get("buys", 0))
        sells  = safe_float(txns24.get("sells", 0))
        txns5  = get_txns(pair, "m5")
        buys5  = safe_float(txns5.get("buys", 0))
        sells5 = safe_float(txns5.get("sells", 0))

        if mode == "momentum":
            # ── MOMENTUM scoring ──

            # Liquidity strength
            if liq >= 200_000: score += 2; reasons.append("Liq>200k")
            elif liq >= 100_000: score += 1; reasons.append("Liq>100k")

            # Volume 1h
            if vol1 >= 100_000: score += 2; reasons.append("Vol1h>100k")
            elif vol1 >= 50_000: score += 1; reasons.append("Vol1h>50k")

            # Volume spike intensity
            if spike >= 10:   score += 3; reasons.append(f"Spike{spike:.0f}x")
            elif spike >= 6:  score += 2; reasons.append(f"Spike{spike:.0f}x")
            elif spike >= 3:  score += 1; reasons.append(f"Spike{spike:.0f}x")

            # 5m buy pressure
            if buys5 > sells5 * 3 and buys5 >= 20:
                score += 3; reasons.append("5mBuyRush")
            elif buys5 > sells5 * 2 and buys5 >= 10:
                score += 2; reasons.append("5mBuys2x")
            elif buys5 > sells5 * 1.5:
                score += 1; reasons.append("5mBuys1.5x")

            # 24h buy ratio
            if sells > 0:
                ratio = buys / sells
                if ratio >= 3.0:   score += 2; reasons.append(f"Buys{ratio:.1f}x")
                elif ratio >= 2.0: score += 1; reasons.append(f"Buys{ratio:.1f}x")

            # Price momentum
            if ch1 >= 50:   score += 3; reasons.append(f"+{ch1:.0f}%1h")
            elif ch1 >= 20: score += 2; reasons.append(f"+{ch1:.0f}%1h")
            elif ch1 >= 10: score += 1; reasons.append(f"+{ch1:.0f}%1h")

            # Market cap (mid range = more room to grow)
            if 500_000 <= mc <= 2_000_000:
                score += 1; reasons.append("MC500k-2M")

        else:
            # ── PUMP / DEX scoring ──

            # Liquidity (real DEX only)
            if dex_type == "real":
                if liq >= 30_000:  score += 1; reasons.append("Liq>30k")
                if liq >= 75_000:  score += 1; reasons.append("Liq>75k")
                if liq >= 150_000: score += 1; reasons.append("Liq>150k")

            # Volume
            if vol24 >= 10_000:  score += 1; reasons.append("Vol>10k")
            if vol24 >= 50_000:  score += 1; reasons.append("Vol>50k")
            if vol1  >= 5_000:   score += 1; reasons.append("Vol1h>5k")
            if vol1  >= 30_000:  score += 1; reasons.append("Vol1h>30k")

            # Vol spike
            if spike > 2:
                score += 2; reasons.append("VolSpike5m")
            elif buys5 > sells5 * 2 and buys5 >= 10:
                score += 1; reasons.append("5mBuySpike")

            # Buy pressure
            if sells > 0:
                ratio = buys / sells
                if ratio >= 3.0:   score += 3; reasons.append(f"Buys{ratio:.1f}x")
                elif ratio >= 2.0: score += 2; reasons.append(f"Buys{ratio:.1f}x")
                elif ratio >= 1.5: score += 1; reasons.append(f"Buys{ratio:.1f}x")

            # MC
            if 0 < mc <= 50_000:    score += 3; reasons.append("MC<50k")
            elif 0 < mc <= 100_000: score += 2; reasons.append("MC<100k")
            elif 0 < mc <= 300_000: score += 1; reasons.append("MC<300k")

            # Age
            if 0 < age <= 5:    score += 3; reasons.append("Age<5m")
            elif 0 < age <= 15: score += 2; reasons.append("Age<15m")
            elif 0 < age <= 30: score += 1; reasons.append("Age<30m")

            # Price momentum
            if ch1 >= 200:   score += 3; reasons.append(f"+{ch1:.0f}%")
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

def format_alert(pair, score, reasons, dex_type, mode,
                 risk_tag, risk_emoji, risk_reasons, risk_pts, holders) -> str:

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
    spike = get_vol_spike_ratio(pair)

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

    # Signal level
    if score >= 13:   sig_emoji, signal = "💎", "MEGA GEM"
    elif score >= 11: sig_emoji, signal = "🚀", "STRONG BUY"
    elif score >= 9:  sig_emoji, signal = "🔥", "HIGH POTENTIAL"
    else:             sig_emoji, signal = "⚡", "WATCH NOW"

    # Mode tag
    if mode == "pump":
        mode_tag = "⚡ PUMP.FUN"
        liq_line = "💧 Liq:      Bonding Curve"
    elif mode == "momentum":
        mode_tag = "📈 MOMENTUM"
        liq_line = f"💧 Liq:      ${liq:,}  (LOCKED)"
    else:
        mode_tag = "🏦 REAL DEX"
        liq_line = f"💧 Liq:      ${liq:,}"

    # Holder line
    if holders:
        holder_line = (
            f"🐋 Holders:  Top1={holders.get('top1',0)}%  "
            f"Top5={holders.get('top5',0)}%"
        )
    else:
        holder_line = "🐋 Holders:  N/A"

    reasons_str = " | ".join(reasons)

    # Spike line for momentum
    spike_line = f"⚡ Vol Spike: {spike:.1f}x normal rate\n" if mode == "momentum" else ""

    msg = (
        f"{sig_emoji} {signal}  [{mode_tag}]\n"
        f"================================\n"
        f"🪙 {name} ({symbol})\n"
        f"🏦 DEX: {dex}\n\n"
        f"⭐ Score:  {score}/15\n"
        f"✅ {reasons_str}\n\n"
        f"━━━━ RISK ━━━━\n"
        f"{risk_emoji} {risk_tag}  ({risk_pts} pts)\n"
        f"⚠️  {risk_reasons}\n"
        f"{holder_line}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{liq_line}\n"
        f"💰 MC:       ${mc:,}\n"
        f"📊 Vol 24h:  ${vol24:,}\n"
        f"📊 Vol 1h:   ${vol1:,}\n"
        f"📊 Vol 5m:   ${vol5m:,}\n"
        f"{spike_line}"
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
                log.info(f"Whale: {short} {side} {token} ${value_usd:.0f}")
        except Exception as e:
            log.error(f"Wallet error: {e}")

# ─────────────────────────────────────────────
#  STATS
# ─────────────────────────────────────────────

def report_stats():
    uptime = int(time.time() - stats["start_time"])
    h, m   = uptime // 3600, (uptime % 3600) // 60
    total  = stats["alerts_pump"] + stats["alerts_dex"] + stats["alerts_momentum"]
    rate   = total / max(uptime / 3600, 0.1)
    msg = (
        f"📊 PRO SNIPER v4.4 STATS\n"
        f"================================\n"
        f"Uptime:        {h}h {m}m\n"
        f"Cycles:        {stats['cycles']}\n"
        f"Pairs Scanned: {stats['pairs_scanned']}\n"
        f"Total Alerts:  {total} ({rate:.1f}/hr)\n"
        f"  Pump.fun:    {stats['alerts_pump']}\n"
        f"  Real DEX:    {stats['alerts_dex']}\n"
        f"  Momentum:    {stats['alerts_momentum']}\n\n"
        f"RISK:\n"
        f"  SAFE:    {stats['safe_count']}\n"
        f"  RISKY:   {stats['risky_count']}\n"
        f"  GAMBLE:  {stats['gamble_skipped']} (filtered)\n\n"
        f"Rugs Skipped:  {stats['rugs_skipped']}\n"
        f"Cache:         {len(seen_tokens)}"
    )
    send_telegram(msg, silent=True)

# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────

def main():
    log.info("=" * 56)
    log.info("   MEMECOIN PRO SNIPER BOT v4.4 - THREE MODE")
    log.info("=" * 56)
    log.info(f"PUMP:     score>={PUMP_MIN_SCORE} | age<{PUMP_MAX_AGE_MIN}m | buys>={PUMP_MIN_BUYS}")
    log.info(f"DEX:      score>={DEX_MIN_SCORE} | liq>=${DEX_MIN_LIQUIDITY:,} | buys>={DEX_MIN_BUYS}")
    log.info(f"MOMENTUM: score>={MOM_MIN_SCORE} | MC>=${MOM_MIN_MC:,} | liq>=${MOM_MIN_LIQUIDITY:,} | spike>={MOM_VOL_SPIKE_RATIO}x")
    log.info(f"Wallets: {len(WALLETS)} | Birdeye: {'ON' if BIRDEYE_KEY else 'OFF'}")
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

                    # Detect mode
                    mode = detect_mode(pair)

                    # Apply correct filter
                    if mode == "momentum":
                        passes, reason = passes_momentum_filters(pair)
                        min_score = MOM_MIN_SCORE
                    elif mode == "pump":
                        passes, reason = passes_pump_filters(pair)
                        min_score = PUMP_MIN_SCORE
                    else:
                        passes, reason = passes_dex_filters(pair)
                        min_score = DEX_MIN_SCORE

                    if not passes:
                        continue

                    # Rug check
                    if baddr and is_rug(baddr):
                        log.info(f"RUG SKIPPED: {sym}")
                        stats["rugs_skipped"] += 1
                        seen_tokens.add(addr)
                        continue

                    # Score
                    score, reasons = score_token(pair, dex_type, mode)
                    if score < min_score:
                        continue

                    # Whale concentration
                    holders = check_whale_concentration(baddr) if baddr else {}

                    # Risk assessment
                    risk_tag, risk_emoji, risk_reasons, risk_pts = assess_risk(
                        pair, dex_type, mode, score, holders
                    )

                    # Skip GAMBLE — too risky
                    if risk_tag == "GAMBLE":
                        log.info(f"GAMBLE SKIPPED: {sym} ({risk_pts}pts)")
                        stats["gamble_skipped"] += 1
                        seen_tokens.add(addr)
                        continue

                    # Track stats
                    if risk_tag == "SAFE":
                        stats["safe_count"] += 1
                    else:
                        stats["risky_count"] += 1

                    seen_tokens.add(addr)
                    msg = format_alert(
                        pair, score, reasons, dex_type, mode,
                        risk_tag, risk_emoji, risk_reasons,
                        risk_pts, holders
                    )

                    log.info(
                        f"ALERT [{score}/15] [{mode.upper()}] "
                        f"[{risk_tag}] {sym} | {' | '.join(reasons)}"
                    )
                    send_telegram(msg)

                    if mode == "pump":
                        stats["alerts_pump"] += 1
                    elif mode == "momentum":
                        stats["alerts_momentum"] += 1
                    else:
                        stats["alerts_dex"] += 1

                    alerts_this_cycle += 1
                    if alerts_this_cycle > 1:
                        time.sleep(0.4)

                except Exception as e:
                    log.error(f"Pair error: {e}")
                    continue

            total = stats["alerts_pump"] + stats["alerts_dex"] + stats["alerts_momentum"]
            log.info(
                f"Alerts: {alerts_this_cycle} | Total: {total} | "
                f"Pump: {stats['alerts_pump']} | "
                f"DEX: {stats['alerts_dex']} | "
                f"Momentum: {stats['alerts_momentum']} | "
                f"Cache: {len(seen_tokens)}"
            )

            if len(seen_tokens) > 5000:
                seen_tokens.clear()
                log.info("Cache cleared")

            time.sleep(SCAN_INTERVAL_SEC)

        except KeyboardInterrupt:
            log.info("Stopped.")
            send_telegram("PRO SNIPER BOT v4.4 STOPPED")
            break
        except Exception as e:
            log.error(f"Main loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
