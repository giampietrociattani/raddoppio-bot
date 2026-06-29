import os
import json
import requests
import time
import base64

SHEET_ID = "14zVe0T-4c33WEcvJ6T0i2gjLOvgD3EH5jXr-gQ9xV1c"

def get_token(creds):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

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
    private_key = serialization.load_pem_private_key(creds["private_key"].encode(), password=None)
    signature = private_key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
    jwt = (msg + b"." + sig_b64).decode()
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion":  jwt,
    }, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]

def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def batch_update(token, data):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchUpdate"
    r = requests.post(url, headers=h(token), json={
        "valueInputOption": "USER_ENTERED",
        "data": data
    }, timeout=15)
    print(f"  batchUpdate: {r.status_code}")
    if r.status_code != 200:
        print(r.text[:300])
    return r

def get_sheet_id(token, sheet_name):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
    r = requests.get(url, headers=h(token), timeout=10)
    sheets = r.json().get("sheets", [])
    for s in sheets:
        if s["properties"]["title"] == sheet_name:
            return s["properties"]["sheetId"]
    return None

def format_cells(token, requests_list):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}:batchUpdate"
    r = requests.post(url, headers=h(token), json={"requests": requests_list}, timeout=15)
    print(f"  formatCells: {r.status_code}")
    return r

# Colori
BLUE_DARK  = {"red": 0.122, "green": 0.306, "blue": 0.475}  # #1F4E79
BLUE_MED   = {"red": 0.173, "green": 0.443, "blue": 0.702}  # #2C71B3
GREEN      = {"red": 0.204, "green": 0.600, "blue": 0.341}  # #349957
YELLOW     = {"red": 0.980, "green": 0.737, "blue": 0.016}  # #FABC04
RED        = {"red": 0.753, "green": 0.114, "blue": 0.157}  # #C01D28
LIGHT_BLUE = {"red": 0.878, "green": 0.925, "blue": 0.973}  # #E0ECF8
LIGHT_GREY = {"red": 0.953, "green": 0.953, "blue": 0.953}  # #F3F3F3
WHITE      = {"red": 1, "green": 1, "blue": 1}

def cell(r, c): return {"rowIndex": r, "columnIndex": c}
def grid(sid, r1, c1, r2, c2): return {"sheetId": sid, "startRowIndex": r1, "startColumnIndex": c1, "endRowIndex": r2, "endColumnIndex": c2}

if __name__ == "__main__":
    import os
    creds_raw = os.environ.get("GOOGLE_CREDENTIALS", "")
    if not creds_raw:
        raise ValueError("GOOGLE_CREDENTIALS secret non configurato")
    creds = json.loads(creds_raw)

    print("Auth...")
    token = get_token(creds)
    sid = get_sheet_id(token, "Dashboard")
    print(f"Dashboard sheetId: {sid}")

    # ── VALORI ──
    # Struttura Dashboard:
    # Riga 1: Titolo principale
    # Riga 3-4: KPI principali (6 KPI)
    # Riga 6: Sezione Rating per Campionato
    # Riga 7: Header tabella campionati
    # Riga 8-21: Dati campionati (14 leghe)
    # Riga 23: Sezione Rating per Giorno
    # Riga 24: Header tabella giorni
    # Riga 25-31: Dati giorni settimana

    # Le formule leggono da Combinazioni (col A=DataAlert, S=EsitoEv1, T=EsitoEv2, U=Giocata?)
    # e da Partite (col C=Campionato, J=Esito)

    values = [
        # R1: Titolo
        ["DASHBOARD — RADDOPPIANDO", "", "", "", "", "", "", ""],
        [""],
        # R3: Label KPI
        ["📊 Alert Totali", "🎯 Giocate", "✅ WIN Totali", "❌ LOSS Totali", "📈 Win Rate", "🏆 Score Medio"],
        # R4: Formule KPI
        [
            "=COUNTA(Combinazioni!A2:A)",                                          # Alert totali
            "=SUMIF(Combinazioni!U2:U;1;Combinazioni!U2:U)",                       # Giocate (colonna U = 1)
            '=COUNTIFS(Combinazioni!U2:U,1,Combinazioni!S2:S,"✅ WIN*")',           # WIN
            '=COUNTIFS(Combinazioni!U2:U,1,Combinazioni!S2:S,"❌ LOSS*")',          # LOSS
            '=IFERROR(COUNTIFS(Combinazioni!U2:U,1,Combinazioni!S2:S,"✅ WIN*")/SUMIF(Combinazioni!U2:U,1,Combinazioni!U2:U),"–")',  # Win Rate
            "=IFERROR(AVERAGEIF(Combinazioni!R2:R;\">0\";Combinazioni!R2:R);\"–\")",  # Score medio
        ],
        [""],
        # R6: Sezione campionati
        ["📋 RATING PER CAMPIONATO", "", "", "", "", "", "", ""],
        ["Campionato", "Alert", "Giocate", "WIN", "LOSS", "Win Rate", "Score Medio"],
    ]

    # Campionati — legge da Partite col C (campionato) e J (esito)
    # e da Combinazioni col C (camp1), K (camp2), U (giocata), S (esito1)
    leghe = [
        "Fifa World Cup",
        "Brazil Campeonato",
        "Brazil Serie B",
        "China Super League",
        "Ireland",
        "Australia A-League",
        "USA MLS",
        "Argentina Primera",
        "Japan J-League",
        "Italy Serie A",
        "England Premier League",
        "Germany Bundesliga",
        "Spain La Liga",
        "France Ligue 1",
    ]

    for lega in leghe:
        l = lega.replace("'", "\\'")
        row = [
            lega,
            f'=COUNTIF(Partite!C2:C,"{l}")',
            f'=COUNTIFS(Partite!C2:C,"{l}",Partite!J2:J,"✅ WIN")+COUNTIFS(Partite!C2:C,"{l}",Partite!J2:J,"❌ LOSS")',
            f'=COUNTIFS(Partite!C2:C,"{l}",Partite!J2:J,"✅ WIN")',
            f'=COUNTIFS(Partite!C2:C,"{l}",Partite!J2:J,"❌ LOSS")',
            f'=IFERROR(COUNTIFS(Partite!C2:C,"{l}",Partite!J2:J,"✅ WIN")/(COUNTIFS(Partite!C2:C,"{l}",Partite!J2:J,"✅ WIN")+COUNTIFS(Partite!C2:C,"{l}",Partite!J2:J,"❌ LOSS")),"–")',
            f'=IFERROR(AVERAGEIF(Partite!C2:C,"{l}",Partite!G2:G),"–")',
        ]
        values.append(row)

    values.append([""])

    # Sezione giorni settimana
    values.append(["📅 RATING PER GIORNO DELLA SETTIMANA", "", "", "", "", "", "", ""])
    values.append(["Giorno", "Alert", "Giocate", "WIN", "LOSS", "Win Rate"])

    giorni = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    # WEEKDAY in Google Sheets: 2=Lun, 3=Mar, 4=Mer, 5=Gio, 6=Ven, 7=Sab, 1=Dom
    weekday_map = {"Lunedì": 2, "Martedì": 3, "Mercoledì": 4, "Giovedì": 5, "Venerdì": 6, "Sabato": 7, "Domenica": 1}

    for giorno in giorni:
        wd = weekday_map[giorno]
        row = [
            giorno,
            f"=SUMPRODUCT((WEEKDAY(Combinazioni!A2:A;2)={wd})*(Combinazioni!A2:A<>\"\"))",
            f"=SUMPRODUCT((WEEKDAY(Combinazioni!A2:A;2)={wd})*(Combinazioni!U2:U=1))",
            f'=SUMPRODUCT((WEEKDAY(Combinazioni!A2:A,2)={wd})*(Combinazioni!U2:U=1)*(Combinazioni!S2:S="✅ WIN"))',
            f'=SUMPRODUCT((WEEKDAY(Combinazioni!A2:A,2)={wd})*(Combinazioni!U2:U=1)*(Combinazioni!S2:S="❌ LOSS"))',
            f'=IFERROR(SUMPRODUCT((WEEKDAY(Combinazioni!A2:A,2)={wd})*(Combinazioni!U2:U=1)*(Combinazioni!S2:S="✅ WIN"))/SUMPRODUCT((WEEKDAY(Combinazioni!A2:A,2)={wd})*(Combinazioni!U2:U=1)),"–")',
        ]
        values.append(row)

    # Scrivi tutti i valori
    print("Scrittura valori...")
    data = [{"range": "Dashboard!A1", "values": values}]
    batch_update(token, data)

    # ── FORMATTAZIONE ──
    print("Formattazione...")
    fmt_requests = []

    # Titolo A1 — grande, bianco su blu scuro
    fmt_requests.append({"mergeCells": {"range": grid(sid,0,0,1,8), "mergeType": "MERGE_ALL"}})
    fmt_requests.append({"repeatCell": {"range": grid(sid,0,0,1,8), "cell": {
        "userEnteredFormat": {
            "backgroundColor": BLUE_DARK,
            "textFormat": {"foregroundColor": WHITE, "fontSize": 16, "bold": True},
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"
        }
    }, "fields": "userEnteredFormat"}})

    # KPI labels riga 3 — sfondo blu medio, testo bianco
    fmt_requests.append({"repeatCell": {"range": grid(sid,2,0,3,6), "cell": {
        "userEnteredFormat": {
            "backgroundColor": BLUE_MED,
            "textFormat": {"foregroundColor": WHITE, "fontSize": 10, "bold": True},
            "horizontalAlignment": "CENTER"
        }
    }, "fields": "userEnteredFormat"}})

    # KPI valori riga 4 — sfondo azzurro chiaro, testo grande
    fmt_requests.append({"repeatCell": {"range": grid(sid,3,0,4,6), "cell": {
        "userEnteredFormat": {
            "backgroundColor": LIGHT_BLUE,
            "textFormat": {"fontSize": 14, "bold": True},
            "horizontalAlignment": "CENTER"
        }
    }, "fields": "userEnteredFormat"}})

    # Win Rate KPI (E4) — formato percentuale
    fmt_requests.append({"repeatCell": {"range": grid(sid,3,4,4,5), "cell": {
        "userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}
    }, "fields": "userEnteredFormat.numberFormat"}})

    # Header sezione campionati riga 6
    fmt_requests.append({"mergeCells": {"range": grid(sid,5,0,6,8), "mergeType": "MERGE_ALL"}})
    fmt_requests.append({"repeatCell": {"range": grid(sid,5,0,6,8), "cell": {
        "userEnteredFormat": {
            "backgroundColor": BLUE_DARK,
            "textFormat": {"foregroundColor": WHITE, "fontSize": 12, "bold": True},
            "horizontalAlignment": "LEFT"
        }
    }, "fields": "userEnteredFormat"}})

    # Header tabella campionati riga 7
    fmt_requests.append({"repeatCell": {"range": grid(sid,6,0,7,7), "cell": {
        "userEnteredFormat": {
            "backgroundColor": BLUE_MED,
            "textFormat": {"foregroundColor": WHITE, "bold": True},
            "horizontalAlignment": "CENTER"
        }
    }, "fields": "userEnteredFormat"}})

    # Righe campionati alternate (8-21)
    for i in range(14):
        bg = LIGHT_BLUE if i % 2 == 0 else WHITE
        fmt_requests.append({"repeatCell": {"range": grid(sid, 7+i, 0, 8+i, 7), "cell": {
            "userEnteredFormat": {"backgroundColor": bg, "horizontalAlignment": "CENTER"}
        }, "fields": "userEnteredFormat"}})

    # Win Rate campionati colonna F (col 5) — formato percentuale
    fmt_requests.append({"repeatCell": {"range": grid(sid,7,5,21,6), "cell": {
        "userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}
    }, "fields": "userEnteredFormat.numberFormat"}})

    # Header sezione giorni
    days_start = 7 + 14 + 1  # = 22 (0-indexed)
    fmt_requests.append({"mergeCells": {"range": grid(sid, days_start, 0, days_start+1, 8), "mergeType": "MERGE_ALL"}})
    fmt_requests.append({"repeatCell": {"range": grid(sid, days_start, 0, days_start+1, 8), "cell": {
        "userEnteredFormat": {
            "backgroundColor": BLUE_DARK,
            "textFormat": {"foregroundColor": WHITE, "fontSize": 12, "bold": True},
            "horizontalAlignment": "LEFT"
        }
    }, "fields": "userEnteredFormat"}})

    # Header tabella giorni
    fmt_requests.append({"repeatCell": {"range": grid(sid, days_start+1, 0, days_start+2, 6), "cell": {
        "userEnteredFormat": {
            "backgroundColor": BLUE_MED,
            "textFormat": {"foregroundColor": WHITE, "bold": True},
            "horizontalAlignment": "CENTER"
        }
    }, "fields": "userEnteredFormat"}})

    # Righe giorni alternate
    for i in range(7):
        bg = LIGHT_BLUE if i % 2 == 0 else WHITE
        fmt_requests.append({"repeatCell": {"range": grid(sid, days_start+2+i, 0, days_start+3+i, 6), "cell": {
            "userEnteredFormat": {"backgroundColor": bg, "horizontalAlignment": "CENTER"}
        }, "fields": "userEnteredFormat"}})

    # Win Rate giorni colonna F (col 5) — formato percentuale
    fmt_requests.append({"repeatCell": {"range": grid(sid, days_start+2, 5, days_start+9, 6), "cell": {
        "userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}
    }, "fields": "userEnteredFormat.numberFormat"}})

    # Larghezze colonne
    fmt_requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 220}, "fields": "pixelSize"
    }})
    for c in range(1, 7):
        fmt_requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c, "endIndex": c+1},
            "properties": {"pixelSize": 110}, "fields": "pixelSize"
        }})

    # Altezza riga titolo e KPI
    fmt_requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 50}, "fields": "pixelSize"
    }})
    fmt_requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 3, "endIndex": 4},
        "properties": {"pixelSize": 40}, "fields": "pixelSize"
    }})

    format_cells(token, fmt_requests)
    print("✅ Dashboard completato!")
