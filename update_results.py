"""
update_results.py
Gira ogni 3h insieme al bot.
Legge le partite con esito TBP dal Foglio3, cerca i risultati
sull'Odds API (scores endpoint), aggiorna il Sheet.
"""
import os
import requests
import logging
from datetime import datetime, timezone
from sheets import _read_range, update_results

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

LEAGUES = [
    "soccer_fifa_world_cup",
    "soccer_brazil_serie_b",
]


def fetch_scores():
    """Recupera i risultati delle partite concluse nelle ultime 3 giorni."""
    risultati = {}
    for league in LEAGUES:
        url = (
            f"https://api.the-odds-api.com/v4/sports/{league}/scores/"
            f"?apiKey={ODDS_API_KEY}&daysFrom=3"
        )
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                log.warning(f"Scores API {league}: {r.status_code}")
                continue
            for game in r.json():
                if not game.get("completed"):
                    continue
                scores = game.get("scores") or []
                score_map = {s["name"]: s["score"] for s in scores if s.get("score") is not None}
                home = game.get("home_team")
                away = game.get("away_team")
                if home not in score_map or away not in score_map:
                    continue
                try:
                    gc = int(score_map[home])
                    go = int(score_map[away])
                except (ValueError, TypeError):
                    continue
                risultati[game["id"]] = {
                    "event_id":   game["id"],
                    "gol_casa":   gc,
                    "gol_ospite": go,
                }
        except Exception as e:
            log.error(f"Errore scores {league}: {e}")

    log.info(f"Risultati trovati: {len(risultati)} partite concluse")
    return list(risultati.values())


def run():
    log.info("=== Avvio update_results ===")

    # Leggi partite TBP dal Foglio3
    rows = _read_range("Partite!J2:J")
    tbp_count = sum(1 for r in rows if r and r[0] in ("⏳ TBP", ""))
    if tbp_count == 0:
        log.info("Nessuna partita da aggiornare")
        return

    log.info(f"Partite da aggiornare: {tbp_count}")
    risultati = fetch_scores()
    if not risultati:
        log.info("Nessun risultato disponibile dall'API")
        return

    update_results(risultati)
    log.info("=== Fine update_results ===")


if __name__ == "__main__":
    run()
