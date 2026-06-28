import os
import json
import logging
import requests
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SHEET_ID = "14zVe0T-4c33WEcvJ6T0i2gjLOvgD3EH5jXr-gQ9xV1c"

LEAGUE_LABEL = {
    "soccer_fifa_world_cup":              "Fifa World Cup",
    "soccer_brazil_campeonato":           "Brazil Campeonato",
    "soccer_brazil_serie_b":              "Brazil Serie B",
    "soccer_china_superliga":             "China Super League",
    "soccer_ireland":                     "Ireland",
    "soccer_australia_aleague":           "Australia A-League",
    "soccer_usa_mls":                     "USA MLS",
    "soccer_argentina_primera_division":  "Argentina Primera",
    "soccer_japan_j_league":              "Japan J-League",
    "soccer_italy_serie_a":               "Italy Serie A",
    "soccer_epl":                         "England Premier League",
    "soccer_germany_bundesliga":          "Germany Bundesliga",
    "soccer_spain_la_liga":               "Spain La Liga",
    "soccer_france_ligue_one":            "France Ligue 1",
}

# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------

def _get_token():
    creds_raw = os.environ.get("GOOGLE_CREDENTIALS", "")
    if not creds_raw:
        raise ValueError("GOOGLE_CREDENTIALS secret non configurato")
    creds = json.loads(creds_raw)

    import time, base64, hashlib, hmac
    from urllib.parse import urlencode

    # JWT header + payload
    now = int(time.time())
    header  = base64.urlsafe_b64encode(json.dumps({"alg":"RS256","typ":"JWT"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss":   creds["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud":   "https://oauth2.googleapis.com/token",
        "iat":   now,
        "exp":   now + 3600,
    }).encode()).rstrip(b"=")

    msg = header + b"." + payload

    # Sign with RSA private key using cryptography lib
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    private_key = serialization.load_pem_private_key(
        creds["private_key"].encode(), password=None
    )
    signature = private_key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")

    jwt = (msg + b"." + sig_b64).decode()

    r = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion":  jwt,
    }, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _headers():
    return {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# SHEET UTILITIES
# ---------------------------------------------------------------------------

def _read_range(range_name):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{range_name}"
    r = requests.get(url, headers=_headers(), timeout=10)
    if r.status_code != 200:
        log.warning(f"Read {range_name}: {r.status_code} {r.text[:100]}")
        return []
    return r.json().get("values", [])


def _append_rows(sheet_name, rows):
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/"
        f"{sheet_name}!A1:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    )
    r = requests.post(url, headers=_headers(), json={"values": rows}, timeout=10)
    if r.status_code not in (200, 201):
        log.error(f"Append {sheet_name}: {r.status_code} {r.text[:200]}")
    else:
        log.info(f"Append {sheet_name}: {len(rows)} righe aggiunte")


def _update_cell(range_name, value):
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/"
        f"{range_name}?valueInputOption=USER_ENTERED"
    )
    r = requests.put(url, headers=_headers(), json={"values": [[value]]}, timeout=10)
    if r.status_code != 200:
        log.error(f"Update {range_name}: {r.status_code} {r.text[:100]}")


def _batch_update(data):
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchUpdate"
    )
    r = requests.post(url, headers=_headers(), json={
        "valueInputOption": "USER_ENTERED",
        "data": data
    }, timeout=10)
    if r.status_code != 200:
        log.error(f"BatchUpdate: {r.status_code} {r.text[:200]}")


# ---------------------------------------------------------------------------
# DEDUPLICATION — Foglio3 colonna P (combo_key) come registro inviati
# ---------------------------------------------------------------------------

def get_sent_keys():
    """Legge tutte le combo_key già inviate dal Foglio3."""
    rows = _read_range("Partite!P2:P")
    return set(r[0] for r in rows if r)


def combo_key(e1, e2):
    """Chiave univoca per una combinata: ordinata per id evento."""
    ids = sorted([e1["id"], e2["id"]])
    return f"{ids[0]}|{ids[1]}"


# ---------------------------------------------------------------------------
# FOGLIO 2 — Combinazioni
# Colonne: A=Data Alert, B=Ora UTC, C=Partita1, D=Campionato1, E=DataGara1,
#           F=Selezione1, G=Quota1, H=Score1, I=Book1,
#           J=Partita2, K=Campionato2, L=DataGara2,
#           M=Selezione2, N=Quota2, O=Score2, P=Book2,
#           Q=QuotaComb, R=ScoreComb, S=EsitoEv1, T=EsitoEv2, U=Giocata?
# ---------------------------------------------------------------------------

def log_combinata(e1, e2, s1, s2, sm, qc, now_str):
    def formatta(iso):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.strftime("%d/%m %H:%M")
        except:
            return iso

    data_alert = now_str[:10]
    ora_alert  = now_str[11:16] + " UTC"

    row = [
        data_alert, ora_alert,
        f"{e1['home']} vs {e1['away']}",
        LEAGUE_LABEL.get(e1["league"], e1["league"]),
        formatta(e1["commence"]),
        e1["etichetta"], e1["quota"], s1, e1["bookmaker"],
        f"{e2['home']} vs {e2['away']}",
        LEAGUE_LABEL.get(e2["league"], e2["league"]),
        formatta(e2["commence"]),
        e2["etichetta"], e2["quota"], s2, e2["bookmaker"],
        qc, sm,
        "⏳ TBP", "⏳ TBP",  # Esito Ev1, Esito Ev2 — aggiornati dopo
        "",  # Giocata? — manuale
    ]
    _append_rows("Combinazioni", [row])
    log.info(f"Combinata loggata: {e1['home']} vs {e1['away']} + {e2['home']} vs {e2['away']}")


# ---------------------------------------------------------------------------
# FOGLIO 3 — Database Partite
# Colonne: A=Data Alert, B=Partita, C=Campionato, D=DataGara, E=Selezione,
#           F=Quota, G=Score, H=Bookmaker, I=Risultato, J=Esito,
#           K=GolCasa, L=GolOspite, M=TotGol, N=EventoID, O=Commence, P=ComboKey
# ---------------------------------------------------------------------------

def log_partite(e1, e2, s1, s2, qc, combo_k, now_str):
    def formatta(iso):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y %H:%M")
        except:
            return iso

    data_alert = now_str[:10]

    for e, s in [(e1, s1), (e2, s2)]:
        row = [
            data_alert,
            f"{e['home']} vs {e['away']}",
            LEAGUE_LABEL.get(e["league"], e["league"]),
            formatta(e["commence"]),
            e["etichetta"],
            e["quota"],
            s,
            e["bookmaker"],
            "",        # Risultato (es. 2-1) — aggiornato dopo
            "⏳ TBP",  # Esito — aggiornato dopo
            "",        # Gol Casa
            "",        # Gol Ospite
            "",        # Tot Gol
            e["id"],
            e["commence"],
            combo_k,
        ]
        _append_rows("Partite", [row])


# ---------------------------------------------------------------------------
# AGGIORNAMENTO ESITI — chiamato da update_results.py
# ---------------------------------------------------------------------------

def calcola_esito(selezione, gol_casa, gol_ospite):
    """Determina WIN/LOSS dato selezione e risultato."""
    tot = gol_casa + gol_ospite
    sel = selezione.lower()

    if "over" in sel:
        try:
            linea = float(sel.split()[1])
            return "✅ WIN" if tot > linea else "❌ LOSS"
        except:
            return "❌ LOSS"
    elif "under" in sel:
        try:
            linea = float(sel.split()[1])
            return "✅ WIN" if tot < linea else "❌ LOSS"
        except:
            return "❌ LOSS"
    elif "vittoria" in sel or sel.endswith("(1)"):
        return "✅ WIN" if gol_casa > gol_ospite else "❌ LOSS"
    elif sel.endswith("(2)"):
        return "✅ WIN" if gol_ospite > gol_casa else "❌ LOSS"
    elif "pareggio" in sel or "(x)" in sel:
        return "✅ WIN" if gol_casa == gol_ospite else "❌ LOSS"
    return "N/D"


def update_results(risultati):
    """
    risultati: lista di dict {event_id, gol_casa, gol_ospite}
    Aggiorna Foglio3 (Partite) e propaga l'esito nel Foglio2 (Combinazioni).
    """
    rows = _read_range("Partite!A2:P")
    if not rows:
        return

    batch = []
    combo_esiti = {}  # combo_key -> {ev_id: esito}

    for i, row in enumerate(rows):
        if len(row) < 14:
            continue
        ev_id     = row[13] if len(row) > 13 else ""
        selezione = row[4]  if len(row) > 4  else ""
        combo_k   = row[15] if len(row) > 15 else ""
        esito_att = row[9]  if len(row) > 9  else ""

        if esito_att not in ("⏳ TBP", ""):
            continue  # già aggiornato

        match = next((r for r in risultati if r["event_id"] == ev_id), None)
        if not match:
            continue

        gc = match["gol_casa"]
        go = match["gol_ospite"]
        risultato = f"{gc}-{go}"
        esito = calcola_esito(selezione, gc, go)
        sheet_row = i + 2  # 1-indexed + header

        batch.append({"range": f"Partite!I{sheet_row}", "values": [[risultato]]})
        batch.append({"range": f"Partite!J{sheet_row}", "values": [[esito]]})
        batch.append({"range": f"Partite!K{sheet_row}", "values": [[gc]]})
        batch.append({"range": f"Partite!L{sheet_row}", "values": [[go]]})
        batch.append({"range": f"Partite!M{sheet_row}", "values": [[gc + go]]})

        log.info(f"Esito: {ev_id} | {selezione} | {risultato} → {esito}")

        if combo_k:
            if combo_k not in combo_esiti:
                combo_esiti[combo_k] = {}
            combo_esiti[combo_k][ev_id] = esito

    if batch:
        _batch_update(batch)

    # Propaga esiti nel Foglio2 (Combinazioni)
    if combo_esiti:
        _aggiorna_combinazioni(combo_esiti)


def _aggiorna_combinazioni(combo_esiti):
    """Aggiorna colonne S (EsitoEv1) e T (EsitoEv2) nel Foglio2."""
    # Leggo Foglio3 per mappare combo_key -> ev_ids in ordine
    partite_rows = _read_range("Partite!A2:P")
    combo_ev_map = {}  # combo_key -> [ev_id1, ev_id2] in ordine di inserimento
    for row in partite_rows:
        if len(row) < 16:
            continue
        ev_id   = row[13]
        combo_k = row[15]
        if combo_k not in combo_ev_map:
            combo_ev_map[combo_k] = []
        if ev_id not in combo_ev_map[combo_k]:
            combo_ev_map[combo_k].append(ev_id)

    # Leggo Foglio2 per trovare le righe da aggiornare
    comb_rows = _read_range("Combinazioni!A2:U")
    batch = []

    for i, row in enumerate(comb_rows):
        # Ricostruisco combo_key dalla riga: non lo salviamo in Foglio2
        # quindi lo cerco tramite partita1 e partita2
        if len(row) < 18:
            continue
        s_esito1 = row[18] if len(row) > 18 else "⏳ TBP"
        s_esito2 = row[19] if len(row) > 19 else "⏳ TBP"
        if s_esito1 not in ("⏳ TBP", "") and s_esito2 not in ("⏳ TBP", ""):
            continue  # già aggiornati entrambi

        sheet_row = i + 2

        # Cerca la combo_key che ha gli stessi eventi
        for combo_k, esiti in combo_esiti.items():
            ev_ids = combo_ev_map.get(combo_k, [])
            if len(ev_ids) < 2:
                continue
            ev1, ev2 = ev_ids[0], ev_ids[1]
            if ev1 in esiti and s_esito1 in ("⏳ TBP", ""):
                batch.append({"range": f"Combinazioni!S{sheet_row}", "values": [[esiti[ev1]]]})
            if ev2 in esiti and s_esito2 in ("⏳ TBP", ""):
                batch.append({"range": f"Combinazioni!T{sheet_row}", "values": [[esiti[ev2]]]})

    if batch:
        _batch_update(batch)
        log.info(f"Combinazioni aggiornate: {len(batch)} celle")
