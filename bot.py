import os
import requests
import itertools
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "")
ODDS_API_KEY      = os.environ.get("ODDS_API_KEY", "")
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY", "")

QUOTA_MIN = float(os.environ.get("QUOTA_MIN", "1.25"))
QUOTA_MAX = float(os.environ.get("QUOTA_MAX", "1.85"))
MIN_SCORE = int(os.environ.get("MIN_SCORE", "0"))

LEAGUES = [
    "soccer_fifa_world_cup",
    "soccer_brazil_campeonato",
    "soccer_brazil_serie_b",
    "soccer_china_superliga",
    "soccer_ireland",
    "soccer_australia_aleague",
    "soccer_usa_mls",
    "soccer_argentina_primera_division",
    "soccer_japan_j_league",
    "soccer_italy_serie_a",
    "soccer_epl",
    "soccer_germany_bundesliga",
    "soccer_spain_la_liga",
    "soccer_france_ligue_one",
]

LEAGUE_TO_FD = {
    "soccer_italy_serie_a":      "SA",
    "soccer_epl":                "PL",
    "soccer_germany_bundesliga": "BL1",
    "soccer_spain_la_liga":      "PD",
    "soccer_france_ligue_one":   "FL1",
}

BOOKMAKERS_EU = ["sisal", "bet365", "unibet", "williamhill", "betfair", "pinnacle", "marathonbet"]

def quota_a_score(q):
    """Converte una quota in score 0-100 basato sulla probabilità implicita.
    Quota 1.25 (80% prob) → score 80
    Quota 1.50 (67% prob) → score 67
    Quota 1.85 (54% prob) → score 54
    Corretto per agio stimato 6%.
    """
    prob_implicita = 1 / q
    prob_reale = prob_implicita * (1 - 0.06)
    return min(round(prob_reale * 100), 100)

def fetch_odds():
    eventi = []
    for league in LEAGUES:
        url = (
            f"https://api.the-odds-api.com/v4/sports/{league}/odds/"
            f"?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h,totals"
            f"&oddsFormat=decimal&dateFormat=iso"
        )
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                log.warning(f"Odds API {league}: {r.status_code} {r.text[:100]}")
                continue
            data = r.json()
            for evento in data:
                migliore = {}
                for bm in evento.get("bookmakers", []):
                    if bm["key"] not in BOOKMAKERS_EU:
                        continue
                    for market in bm.get("markets", []):
                        mkey = market["key"]
                        for outcome in market.get("outcomes", []):
                            q = outcome.get("price", 0)
                            if QUOTA_MIN <= q <= QUOTA_MAX:
                                ok_key = f"{mkey}_{outcome['name']}_{outcome.get('point','')}"
                                if ok_key not in migliore or q > migliore[ok_key]["quota"]:
                                    migliore[ok_key] = {
                                        "bookmaker": bm["key"],
                                        "quota": q,
                                        "outcome": outcome,
                                        "mkey": mkey,
                                    }
                for ok_key, best in migliore.items():
                    outcome = best["outcome"]
                    mkey = best["mkey"]
                    q = best["quota"]
                    nome = outcome["name"]
                    punto = outcome.get("point", "")
                    if mkey == "totals":
                        etichetta = f"{nome} {punto} goal"
                    elif mkey == "h2h":
                        mappa = {
                            "home": f"Vittoria {evento['home_team']} (1)",
                            "away": f"Vittoria {evento['away_team']} (2)",
                            "Draw": "Pareggio (X)"
                        }
                        etichetta = mappa.get(nome, nome)
                    else:
                        etichetta = nome
                    eventi.append({
                        "id":        evento["id"],
                        "home":      evento["home_team"],
                        "away":      evento["away_team"],
                        "league":    league,
                        "commence":  evento["commence_time"],
                        "mercato":   mkey,
                        "etichetta": etichetta,
                        "quota":     q,
                        "outcome":   nome,
                        "point":     punto,
                        "bookmaker": best["bookmaker"],
                    })
        except Exception as e:
            log.error(f"Errore fetch {league}: {e}")
    log.info(f"Quote nel range {QUOTA_MIN}-{QUOTA_MAX} trovate: {len(eventi)}")
    return eventi

_cache = {}

def get_team_stats(team_name, comp):
    key = f"{team_name}_{comp}"
    if key in _cache:
        return _cache[key]
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        r = requests.get(
            f"https://api.football-data.org/v4/competitions/{comp}/teams",
            headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        teams = r.json().get("teams", [])
        team = next((t for t in teams if team_name.lower() in t["name"].lower()
                     or (t.get("shortName") and team_name.lower() in t["shortName"].lower())), None)
        if not team:
            return None
        r2 = requests.get(
            f"https://api.football-data.org/v4/teams/{team['id']}/matches?status=FINISHED&limit=10",
            headers=headers, timeout=10)
        if r2.status_code != 200:
            return None
        matches = r2.json().get("matches", [])
        gs_list, gc_list, results = [], [], []
        for m in matches:
            hs  = m["score"]["fullTime"]["home"]
            as_ = m["score"]["fullTime"]["away"]
            if hs is None or as_ is None:
                continue
            is_home = m["homeTeam"]["id"] == team["id"]
            gs = hs if is_home else as_
            gc = as_ if is_home else hs
            gs_list.append(gs); gc_list.append(gc)
            results.append("W" if gs > gc else ("D" if gs == gc else "L"))
        n = len(gs_list)
        if n == 0:
            return None
        stats = {
            "avg_scored":   round(sum(gs_list)/n, 2),
            "avg_conceded": round(sum(gc_list)/n, 2),
            "over25_pct":   round(sum(1 for g,c in zip(gs_list,gc_list) if g+c>2.5)/n*100, 1),
            "gg_pct":       round(sum(1 for g,c in zip(gs_list,gc_list) if g>0 and c>0)/n*100, 1),
            "forma":        "".join(results[-5:]),
        }
        _cache[key] = stats
        return stats
    except Exception as e:
        log.warning(f"Stats error {team_name}: {e}")
        return None

def calcola_score(evento, sh, sa):
    """Score 0-100 con tre livelli:
    1. Se statistiche disponibili: usa dati storici (Over%, GG%, forma)
    2. Se no statistiche: usa probabilità implicita della quota
    3. Bonus/malus coerenza mercato
    """
    mercato = evento["mercato"]
    outcome = evento["outcome"]
    quota   = evento["quota"]
    score, bd = 0, []

    if mercato == "totals" and sh and sa:
        # Score da statistiche storiche
        if outcome == "Over":
            p = (sh["over25_pct"] + sa["over25_pct"]) / 2
        else:
            p = (100 - sh["over25_pct"] + 100 - sa["over25_pct"]) / 2
        s = round(p * 0.8)
        score += s
        bd.append(f"Stat storiche Over/Under: {p:.1f}% → +{s}pt")

    elif mercato == "h2h" and sh and sa:
        # Score da forma recente
        forma = sh["forma"] if outcome == "home" else (sa["forma"] if outcome == "away" else "")
        pts = sum({"W":3,"D":1,"L":0}.get(c,0) for c in forma[-5:])
        s = round(pts / 15 * 60)
        score += s
        bd.append(f"Forma recente: {forma} → +{s}pt")

    else:
        # Score da probabilità implicita della quota (NUOVO)
        s = quota_a_score(quota)
        score += s
        prob_pct = round((1/quota) * 100, 1)
        bd.append(f"Prob. implicita quota {quota}: {prob_pct}% → score {s}/100")

    return min(score, 100), bd

def score_combinata(e1, e2, s1, s2):
    """Score finale della combinata con bonus coerenza mercati."""
    sm = (s1 + s2) / 2

    # Bonus se i due mercati si bilanciano (Over+Under o h2h opposte)
    m1, m2 = e1["mercato"], e2["mercato"]
    o1, o2 = e1["outcome"], e2["outcome"]
    if m1 == "totals" and m2 == "totals" and o1 != o2:
        sm += 5
    # Malus se stesso mercato stesso segno (Over+Over o Under+Under)
    if m1 == "totals" and m2 == "totals" and o1 == o2:
        sm -= 3

    return round(sm)

def trova_combinazioni(eventi):
    now = datetime.now(timezone.utc)
    combos = []
    for e1, e2 in itertools.combinations(eventi, 2):
        if e1["id"] == e2["id"]:
            continue
        try:
            t1 = datetime.fromisoformat(e1["commence"].replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(e2["commence"].replace("Z", "+00:00"))
            ore1 = (t1 - now).total_seconds() / 3600
            ore2 = (t2 - now).total_seconds() / 3600
            if not (0 <= ore1 <= 48) or not (0 <= ore2 <= 48):
                continue
        except:
            pass
        qc = round(e1["quota"] * e2["quota"], 4)
        if 1.60 <= qc <= 2.60:
            combos.append((e1, e2, qc))
    # Ordina per quota combinata più vicina a 2.00
    combos.sort(key=lambda x: abs(x[2] - 2.00))
    return combos

def formatta_data(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d/%m %H:%M")
    except:
        return iso

def emoji_forma(f):
    return "".join({"W":"✅","D":"➖","L":"❌"}.get(c,c) for c in f)

def emoji_score(s):
    return "🟢" if s >= 65 else ("🟡" if s >= 55 else "🔴")

def invia_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }, timeout=10)
        if r.status_code == 200:
            log.info("Messaggio Telegram inviato ✓")
        else:
            log.error(f"Telegram error: {r.status_code} {r.text}")
    except Exception as e:
        log.error(f"Telegram send error: {e}")

def run():
    log.info("=== Avvio ciclo bot ===")
    log.info(f"Range quote: {QUOTA_MIN} - {QUOTA_MAX} | MIN_SCORE: {MIN_SCORE}")
    _cache.clear()
    eventi = fetch_odds()
    if not eventi:
        invia_telegram(
            f"ℹ️ *Nessuna quota nel range {QUOTA_MIN}–{QUOTA_MAX} trovata*\n"
            f"_{datetime.now(timezone.utc).strftime('%d/%m %H:%M UTC')}_"
        )
        return
    combos = trova_combinazioni(eventi)
    if not combos:
        invia_telegram(
            f"ℹ️ *Nessuna combinata valida nelle prossime 48h*\n"
            f"_{datetime.now(timezone.utc).strftime('%d/%m %H:%M UTC')}_"
        )
        return

    inviate = 0
    usati = set()

    for e1, e2, qc in combos:
        # Evita duplicati — ogni partita appare al massimo una volta
        if e1["id"] in usati or e2["id"] in usati:
            continue

        comp1 = LEAGUE_TO_FD.get(e1["league"])
        comp2 = LEAGUE_TO_FD.get(e2["league"])
        sh1 = get_team_stats(e1["home"], comp1) if comp1 else None
        sa1 = get_team_stats(e1["away"], comp1) if comp1 else None
        sh2 = get_team_stats(e2["home"], comp2) if comp2 else None
        sa2 = get_team_stats(e2["away"], comp2) if comp2 else None

        s1, bd1 = calcola_score(e1, sh1, sa1)
        s2, bd2 = calcola_score(e2, sh2, sa2)
        sm = score_combinata(e1, e2, s1, s2)

        log.info(f"{e1['home']} vs {e1['away']} ({e1['quota']}) + {e2['home']} vs {e2['away']} ({e2['quota']}) | qComb={qc} | score={sm}")

        if sm < MIN_SCORE:
            log.info(f"  Skip — score {sm} < MIN_SCORE {MIN_SCORE}")
            continue

        def blocco(e, s, bd, sh, sa):
            lines = [
                f"📌 *{e['home']} vs {e['away']}*",
                f"   🏆 {e['league'].replace('soccer_','').replace('_',' ').title()}",
                f"   🕐 {formatta_data(e['commence'])}",
                f"   📊 *{e['etichetta']}* | Quota: *{e['quota']}* ({e.get('bookmaker','?')})",
                f"   {emoji_score(s)} Score: *{s}/100*",
            ]
            if sh:
                lines.append(f"   🏠 {e['home']}: {sh['avg_scored']}⚽/g | Over25: {sh['over25_pct']}% | GG: {sh['gg_pct']}% | {emoji_forma(sh['forma'])}")
            if sa:
                lines.append(f"   ✈️ {e['away']}: {sa['avg_scored']}⚽/g | Over25: {sa['over25_pct']}% | GG: {sa['gg_pct']}% | {emoji_forma(sa['forma'])}")
            for b in bd:
                lines.append(f"   ↳ {b}")
            return "\n".join(lines)

        msg = f"""🔔 *COMBINATA TROVATA* {emoji_score(sm)} Score: *{sm}/100*
_{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}_

━━━━━━━━━━━━━━━━━━━
{blocco(e1, s1, bd1, sh1, sa1)}

━━━━━━━━━━━━━━━━━━━
{blocco(e2, s2, bd2, sh2, sa2)}

━━━━━━━━━━━━━━━━━━━
💰 *Quota combinata: {e1['quota']} × {e2['quota']} = {qc}*
📉 Prob. reale stimata: ~{round((1/e1['quota'])*(1/e2['quota'])*0.93*100,1)}%
⚠️ _Verifica la quota su Sisal prima di giocare_
🔗 tinyurl.com/raddoppiando"""

        invia_telegram(msg)
        usati.add(e1["id"])
        usati.add(e2["id"])
        inviate += 1

        if inviate >= 3:
            break

    if inviate == 0:
        invia_telegram(
            f"ℹ️ *Nessuna combinata valida nelle prossime 48h*\n"
            f"_{datetime.now(timezone.utc).strftime('%d/%m %H:%M UTC')}_"
        )
    log.info(f"=== Fine ciclo — {inviate} messaggi inviati ===")

if __name__ == "__main__":
    run()
