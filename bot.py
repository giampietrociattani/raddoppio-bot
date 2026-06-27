import os
import requests
import itertools
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Configurazione ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ODDS_API_KEY     = os.environ.get("ODDS_API_KEY", "")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY", "")
FOOTBALL_DATA_KEY= os.environ.get("FOOTBALL_DATA_KEY", "")

QUOTA_MIN = float(os.environ.get("QUOTA_MIN", "1.30"))
QUOTA_MAX = float(os.environ.get("QUOTA_MAX", "1.65"))
MIN_SCORE = int(os.environ.get("MIN_SCORE", "50"))

# Mercati da cercare (The Odds API market keys)
MERCATI = ["h2h", "totals", "btts"]

# League keys su The Odds API
LEAGUES = [
    "soccer_fifa_world_cup",
    "soccer_usa_mls",
    "soccer_brazil_campeonato",
    "soccer_argentina_primera_division",
    "soccer_japan_j_league",
    "soccer_italy_serie_a",
    "soccer_epl",
    "soccer_germany_bundesliga",
    "soccer_spain_la_liga",
    "soccer_france_ligue_one",
]

# Mapping mercato → etichetta leggibile
LABEL_MAP = {
    "h2h":    {"1": "Vittoria Casa (1)", "2": "Vittoria Ospite (2)", "Draw": "Pareggio (X)"},
    "totals":  {},   # popolato dinamicamente: Over/Under X.X
    "btts":   {"Yes": "Goal/Goal (GG)", "No": "No Goal (NG)"},
}

# ── The Odds API ──────────────────────────────────────────────────────────────
def fetch_odds():
    """Scarica tutte le quote Sisal per le leghe configurate."""
    eventi = []
    for league in LEAGUES:
        for mercato in MERCATI:
            url = (
                f"https://api.the-odds-api.com/v4/sports/{league}/odds/"
                f"?apiKey={ODDS_API_KEY}&regions=eu&markets={mercato}"
                f"&bookmakers=sisal&oddsFormat=decimal&dateFormat=iso"
            )
            try:
                r = requests.get(url, timeout=10)
                if r.status_code != 200:
                    log.warning(f"Odds API {league}/{mercato}: {r.status_code}")
                    continue
                data = r.json()
                for evento in data:
                    for bm in evento.get("bookmakers", []):
                        if bm["key"] != "sisal":
                            continue
                        for market in bm.get("markets", []):
                            for outcome in market.get("outcomes", []):
                                q = outcome.get("price", 0)
                                if QUOTA_MIN <= q <= QUOTA_MAX:
                                    nome = outcome["name"]
                                    # Etichetta leggibile
                                    if mercato == "totals":
                                        punto = outcome.get("point", "")
                                        etichetta = f"{nome} {punto} goal"
                                    elif mercato == "h2h":
                                        etichetta = LABEL_MAP["h2h"].get(nome, nome)
                                    else:
                                        etichetta = LABEL_MAP["btts"].get(nome, nome)

                                    eventi.append({
                                        "id":        evento["id"],
                                        "home":      evento["home_team"],
                                        "away":      evento["away_team"],
                                        "league":    league,
                                        "commence":  evento["commence_time"],
                                        "mercato":   mercato,
                                        "etichetta": etichetta,
                                        "quota":     q,
                                        "outcome":   nome,
                                        "point":     outcome.get("point"),
                                    })
            except Exception as e:
                log.error(f"Errore fetch odds {league}/{mercato}: {e}")
    log.info(f"Quote nel range trovate: {len(eventi)}")
    return eventi


# ── Football Data API (statistiche) ──────────────────────────────────────────
# Mapping league key → football-data.org competition code
LEAGUE_TO_FD = {
    "soccer_italy_serie_a":         "SA",
    "soccer_italy_serie_b":         "SB",
    "soccer_epl":                   "PL",
    "soccer_germany_bundesliga":    "BL1",
    "soccer_spain_la_liga":         "PD",
    "soccer_france_ligue_one":      "FL1",
    "soccer_uefa_champs_league":    "CL",
}

_team_stats_cache = {}

def get_team_stats_fd(team_name, competition_code):
    """Recupera le ultime 10 partite di una squadra da football-data.org."""
    cache_key = f"{team_name}_{competition_code}"
    if cache_key in _team_stats_cache:
        return _team_stats_cache[cache_key]

    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    # Cerca la squadra per nome
    url = f"https://api.football-data.org/v4/competitions/{competition_code}/teams"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        teams = r.json().get("teams", [])
        team = next((t for t in teams if team_name.lower() in t["name"].lower()
                     or (t.get("shortName") and team_name.lower() in t["shortName"].lower())), None)
        if not team:
            return None
        team_id = team["id"]

        # Ultime partite
        url2 = f"https://api.football-data.org/v4/teams/{team_id}/matches?status=FINISHED&limit=10"
        r2 = requests.get(url2, headers=headers, timeout=10)
        if r2.status_code != 200:
            return None
        matches = r2.json().get("matches", [])

        goals_scored = []
        goals_conceded = []
        results = []
        for m in matches:
            home_id = m["homeTeam"]["id"]
            hs = m["score"]["fullTime"]["home"]
            as_ = m["score"]["fullTime"]["away"]
            if hs is None or as_ is None:
                continue
            if home_id == team_id:
                goals_scored.append(hs)
                goals_conceded.append(as_)
                results.append("W" if hs > as_ else ("D" if hs == as_ else "L"))
            else:
                goals_scored.append(as_)
                goals_conceded.append(hs)
                results.append("W" if as_ > hs else ("D" if as_ == hs else "L"))

        n = len(goals_scored)
        if n == 0:
            return None

        over25 = sum(1 for gs, gc in zip(goals_scored, goals_conceded) if gs + gc > 2.5) / n
        gg     = sum(1 for gs, gc in zip(goals_scored, goals_conceded) if gs > 0 and gc > 0) / n
        avg_scored    = sum(goals_scored) / n
        avg_conceded  = sum(goals_conceded) / n
        forma = "".join(results[-5:])

        stats = {
            "avg_scored":   round(avg_scored, 2),
            "avg_conceded": round(avg_conceded, 2),
            "over25_pct":   round(over25 * 100, 1),
            "gg_pct":       round(gg * 100, 1),
            "forma":        forma,
            "partite":      n,
        }
        _team_stats_cache[cache_key] = stats
        return stats
    except Exception as e:
        log.warning(f"FD stats error {team_name}: {e}")
        return None


def get_h2h_fd(home, away, competition_code):
    """Head to head ultimi 5 incontri tra le due squadre."""
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    url = f"https://api.football-data.org/v4/competitions/{competition_code}/teams"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        teams = r.json().get("teams", [])
        def find_team(name):
            return next((t for t in teams if name.lower() in t["name"].lower()
                         or (t.get("shortName") and name.lower() in t["shortName"].lower())), None)
        th = find_team(home)
        ta = find_team(away)
        if not th or not ta:
            return None

        url2 = f"https://api.football-data.org/v4/teams/{th['id']}/matches?status=FINISHED&limit=20"
        r2 = requests.get(url2, headers=headers, timeout=10)
        if r2.status_code != 200:
            return None
        matches = [m for m in r2.json().get("matches", [])
                   if m["homeTeam"]["id"] == ta["id"] or m["awayTeam"]["id"] == ta["id"]][:5]
        if not matches:
            return None

        over25_h2h = sum(1 for m in matches
                         if (m["score"]["fullTime"]["home"] or 0) + (m["score"]["fullTime"]["away"] or 0) > 2.5)
        gg_h2h = sum(1 for m in matches
                     if (m["score"]["fullTime"]["home"] or 0) > 0 and (m["score"]["fullTime"]["away"] or 0) > 0)
        return {
            "partite":    len(matches),
            "over25_h2h": over25_h2h,
            "gg_h2h":     gg_h2h,
        }
    except Exception as e:
        log.warning(f"H2H error {home} vs {away}: {e}")
        return None


# ── Score algoritmo ────────────────────────────────────────────────────────────
def calcola_score(evento, stats_home, stats_away, h2h):
    """Score 0–100 basato su statistiche. Restituisce score e breakdown."""
    mercato  = evento["mercato"]
    outcome  = evento["outcome"]
    point    = evento.get("point")
    quota    = evento["quota"]
    score    = 0
    breakdown = []

    # Probabilità implicita dalla quota (con agio stimato 7%)
    p_implicita = (1 / quota) * (1 - 0.035)  # correzione agio singola

    if mercato == "totals" and stats_home and stats_away:
        soglia = float(point) if point else 2.5
        avg_totale = stats_home["avg_scored"] + stats_away["avg_conceded"] * 0.5 + \
                     stats_away["avg_scored"] + stats_home["avg_conceded"] * 0.5
        avg_totale /= 2 * 0.7 + 0.3  # normalizzazione

        if outcome == "Over":
            p_stat = stats_home["over25_pct"] / 100 * 0.5 + stats_away["over25_pct"] / 100 * 0.5
            media_pts = min(avg_totale / soglia, 1.0)
            s = round((p_stat * 50 + media_pts * 30))
            score += s
            breakdown.append(f"Over {soglia}: stat combinata {p_stat*100:.0f}% → +{s}pt")
        else:
            p_stat = (100 - stats_home["over25_pct"]) / 100 * 0.5 + (100 - stats_away["over25_pct"]) / 100 * 0.5
            s = round(p_stat * 50)
            score += s
            breakdown.append(f"Under {soglia}: stat combinata {p_stat*100:.0f}% → +{s}pt")

        if h2h:
            if outcome == "Over":
                h2h_pct = h2h["over25_h2h"] / h2h["partite"]
            else:
                h2h_pct = 1 - h2h["over25_h2h"] / h2h["partite"]
            s2 = round(h2h_pct * 20)
            score += s2
            breakdown.append(f"H2H {h2h['over25_h2h']}/{h2h['partite']} Over → +{s2}pt")

    elif mercato == "btts" and stats_home and stats_away:
        if outcome == "Yes":
            p_stat = stats_home["gg_pct"] / 100 * 0.5 + stats_away["gg_pct"] / 100 * 0.5
        else:
            p_stat = (100 - stats_home["gg_pct"]) / 100 * 0.5 + (100 - stats_away["gg_pct"]) / 100 * 0.5
        s = round(p_stat * 70)
        score += s
        breakdown.append(f"GG/NG stat: {p_stat*100:.0f}% → +{s}pt")
        if h2h:
            h2h_pct = h2h["gg_h2h"] / h2h["partite"] if outcome == "Yes" else 1 - h2h["gg_h2h"] / h2h["partite"]
            s2 = round(h2h_pct * 20)
            score += s2
            breakdown.append(f"H2H GG {h2h['gg_h2h']}/{h2h['partite']} → +{s2}pt")

    elif mercato == "h2h" and stats_home and stats_away:
        # Per 1X2 usiamo la forma
        forma_score = 0
        if outcome == "1":
            for r in stats_home.get("forma", "")[-5:]:
                forma_score += {"W": 3, "D": 1, "L": 0}.get(r, 0)
            s = round(forma_score / 15 * 60)
        elif outcome == "2":
            for r in stats_away.get("forma", "")[-5:]:
                forma_score += {"W": 3, "D": 1, "L": 0}.get(r, 0)
            s = round(forma_score / 15 * 60)
        else:
            s = 40  # pareggio: score base neutro
        score += s
        breakdown.append(f"Forma: {s}pt")
    else:
        # Nessuna stat disponibile — score base dalla quota
        score = 45
        breakdown.append("Nessuna statistica disponibile — score base 45")

    score = min(score, 100)
    return score, breakdown


# ── Trova combinazioni ─────────────────────────────────────────────────────────
def trova_combinazioni(eventi):
    """Crea coppie di eventi diversi con quota combinata intorno a 2.00."""
    combinazioni = []
    for e1, e2 in itertools.combinations(eventi, 2):
        # No stesso match
        if e1["id"] == e2["id"]:
            continue
        q_comb = round(e1["quota"] * e2["quota"], 4)
        # Quota combinata tra 1.70 e 2.40
        if 1.70 <= q_comb <= 2.40:
            combinazioni.append((e1, e2, q_comb))
    # Ordina per quota combinata più vicina a 2.00
    combinazioni.sort(key=lambda x: abs(x[2] - 2.00))
    return combinazioni[:5]  # max 5 combinazioni per ciclo


# ── Messaggio Telegram ─────────────────────────────────────────────────────────
def formatta_data(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m %H:%M")
    except:
        return iso_str

def emoji_score(s):
    if s >= 75: return "🟢"
    if s >= 55: return "🟡"
    return "🔴"

def emoji_forma(f):
    return "".join({"W": "✅", "D": "➖", "L": "❌"}.get(c, c) for c in f)

def costruisci_messaggio(e1, e2, q_comb, score1, bd1, stats1h, stats1a, score2, bd2, stats2h, stats2a):
    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    score_medio = round((score1 + score2) / 2)

    def blocco_evento(e, score, bd, sh, sa):
        lines = []
        lines.append(f"📌 *{e['home']} vs {e['away']}*")
        lines.append(f"   🏆 {e['league'].replace('soccer_','').replace('_',' ').title()}")
        lines.append(f"   🕐 {formatta_data(e['commence'])}")
        lines.append(f"   📊 Mercato: *{e['etichetta']}*")
        lines.append(f"   💶 Quota Sisal: *{e['quota']}*")
        lines.append(f"   {emoji_score(score)} Score: *{score}/100*")
        if sh:
            lines.append(f"   🏠 {e['home']}: media {sh['avg_scored']}⚽ segnati | Over25: {sh['over25_pct']}% | GG: {sh['gg_pct']}% | Forma: {emoji_forma(sh['forma'])}")
        if sa:
            lines.append(f"   ✈️ {e['away']}: media {sa['avg_scored']}⚽ segnati | Over25: {sa['over25_pct']}% | GG: {sa['gg_pct']}% | Forma: {emoji_forma(sa['forma'])}")
        for b in bd:
            lines.append(f"   ↳ {b}")
        return "\n".join(lines)

    msg = f"""🔔 *COMBINATA TROVATA* — Score medio: {emoji_score(score_medio)} *{score_medio}/100*
_{ts}_

━━━━━━━━━━━━━━━━━━━
{blocco_evento(e1, score1, bd1, stats1h, stats1a)}

━━━━━━━━━━━━━━━━━━━
{blocco_evento(e2, score2, bd2, stats2h, stats2a)}

━━━━━━━━━━━━━━━━━━━
💰 *Quota combinata: {e1['quota']} × {e2['quota']} = {q_comb}*
📉 Prob. reale stimata: ~{round((1/e1['quota'])*(1/e2['quota'])*0.93*100, 1)}%
⚠️ _Agio doppio sulla combinata — vedi app per EV esatto_
"""
    return msg


def invia_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info("Messaggio Telegram inviato")
        else:
            log.error(f"Telegram error: {r.status_code} {r.text}")
    except Exception as e:
        log.error(f"Telegram send error: {e}")


def invia_nessun_risultato():
    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    msg = f"ℹ️ *Nessuna combinata trovata* _{ts}_\nNessuna coppia di eventi nel range {QUOTA_MIN}–{QUOTA_MAX} con quota combinata 1.70–2.40."
    invia_telegram(msg)


# ── Ciclo principale ──────────────────────────────────────────────────────────
def run():
    log.info("=== Avvio ciclo bot ===")
    _team_stats_cache.clear()

    eventi = fetch_odds()
    if not eventi:
        log.info("Nessun evento nel range quote")
        invia_nessun_risultato()
        return

    combinazioni = trova_combinazioni(eventi)
    if not combinazioni:
        log.info("Nessuna combinazione valida trovata")
        invia_nessun_risultato()
        return

    inviate = 0
    for e1, e2, q_comb in combinazioni:
        comp1 = LEAGUE_TO_FD.get(e1["league"])
        comp2 = LEAGUE_TO_FD.get(e2["league"])

        sh1 = get_team_stats_fd(e1["home"], comp1) if comp1 else None
        sa1 = get_team_stats_fd(e1["away"], comp1) if comp1 else None
        h2h1 = get_h2h_fd(e1["home"], e1["away"], comp1) if comp1 else None

        sh2 = get_team_stats_fd(e2["home"], comp2) if comp2 else None
        sa2 = get_team_stats_fd(e2["away"], comp2) if comp2 else None
        h2h2 = get_h2h_fd(e2["home"], e2["away"], comp2) if comp2 else None

        score1, bd1 = calcola_score(e1, sh1, sa1, h2h1)
        score2, bd2 = calcola_score(e2, sh2, sa2, h2h2)
        score_medio = (score1 + score2) / 2

        log.info(f"Combo: {e1['home']} vs {e1['away']} ({e1['quota']}) + {e2['home']} vs {e2['away']} ({e2['quota']}) | Score: {score_medio:.0f}")

        if score_medio >= MIN_SCORE:
            msg = costruisci_messaggio(e1, e2, q_comb, score1, bd1, sh1, sa1, score2, bd2, sh2, sa2)
            invia_telegram(msg)
            inviate += 1

    if inviate == 0:
        log.info(f"Tutte le combinazioni sotto il MIN_SCORE ({MIN_SCORE})")
        invia_nessun_risultato()

    log.info(f"=== Ciclo completato — {inviate} messaggi inviati ===")


if __name__ == "__main__":
    run()
