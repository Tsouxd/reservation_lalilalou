import os
import json
import base64
import string
import random
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from flask import Flask, render_template, request, jsonify

import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()
app = Flask(__name__)

# --- CONFIGURATION GMAIL API ---
GMAIL_CLIENT_ID = os.environ.get('GMAIL_CLIENT_ID')
GMAIL_CLIENT_SECRET = os.environ.get('GMAIL_CLIENT_SECRET')
GMAIL_REFRESH_TOKEN = os.environ.get('GMAIL_REFRESH_TOKEN')
MAIL_USER = os.environ.get('MAIL_USER', 'tsourakotoson0@gmail.com')

def get_gmail_service():
    creds = Credentials(None, refresh_token=GMAIL_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token",
                        client_id=GMAIL_CLIENT_ID, client_secret=GMAIL_CLIENT_SECRET)
    if creds.expired:
        creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)

def send_gmail_api(to, subject, body):
    try:
        service = get_gmail_service()
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={'raw': raw}).execute()
        return True
    except Exception as e:
        print(f"Erreur API Gmail: {e}")
        return False

# --- CONFIGURATION GOOGLE SHEETS ---
def get_google_sheet(worksheet_name=None):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GOOGLE_CREDS")
    if creds_json:
        if creds_json.startswith("'") and creds_json.endswith("'"): creds_json = creds_json[1:-1]
        creds_dict = json.loads(creds_json)
        if 'private_key' in creds_dict:
            creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    
    client = gspread.authorize(creds)
    spreadsheet = client.open("suivi_reservation_lalilalou")
    if worksheet_name:
        return spreadsheet.worksheet(worksheet_name)
    return spreadsheet.sheet1

# --- FONCTION UTILITAIRE : CALCUL DU RESTE À PAYER ---
def get_balance(total_prix_str):
    try:
        total = int(''.join(filter(str.isdigit, total_prix_str)))
        return f"{total - 10000} ariary"
    except:
        return "à calculer"

# --- LOGIQUE D'ARCHIVAGE AUTOMATIQUE ---
def archive_old_records():
    print(f"[{datetime.now()}] Debut de l'archivage...")
    try:
        sheet_main = get_google_sheet()
        sheet_archive = get_google_sheet("Archives")
        all_rows = sheet_main.get_all_values()
        limite_date = datetime.now() - timedelta(days=30)
        rows_to_move = []
        indices_to_delete = []

        for i, row in enumerate(all_rows):
            if i == 0: continue
            if len(row) > 7 and row[7]:
                try:
                    date_rdv = datetime.strptime(row[7].strip(), "%Y-%m-%d")
                    if date_rdv < limite_date:
                        rows_to_move.append(row)
                        indices_to_delete.append(i + 1)
                except Exception:
                    continue

        if rows_to_move:
            sheet_archive.append_rows(rows_to_move)
            indices_to_delete.sort(reverse=True)
            for idx in indices_to_delete:
                sheet_main.delete_rows(idx)
            print(f"Succes : {len(rows_to_move)} lignes archivees.")
        return f"{len(rows_to_move)} lignes deplacees"
    except Exception as e:
        print(f"Erreur archivage : {e}")
        return str(e)
    
# --- LOGIQUE DE TRAITEMENT AUTOMATIQUE (Confirmations & Rappels) ---
def trigger_auto_tasks():
    print(f"[{datetime.now()}] Analyse du planning...")
    try:
        sheet = get_google_sheet()
        all_rows = sheet.get_all_values()
        demain_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        for i, row in enumerate(all_rows):
            if i == 0: continue 

            if len(row) >= 12:
                client_nom = row[1]; client_email = row[2]; service_nom = row[5]
                date_rdv = row[7]; heure_rdv = row[8]; total_prix = row[9]
                statut = row[11].strip().upper()
                rappel_fait = row[12].upper() if len(row) > 12 else "NON"
                ref_code = row[13] if len(row) > 13 else "N/A"
                confirm_faite = row[14].upper() if len(row) > 14 else "NON"

                solde = get_balance(total_prix)

                # --- 1. EMAIL DE CONFIRMATION (Acompte bien reçu) ---
                if statut == "CONFIRMÉ" and confirm_faite != "OUI":
                    subject_c = f"Confirmation de reservation : Reference {ref_code}"
                    body_c = f"""Bonjour {client_nom},

Nous vous confirmons la bonne reception de votre acompte de 10 000 ariary. Votre reservation chez Lalilalou est desormais validee.

Details de la prestation :
-------------------------------------------
Reference : {ref_code}
Service : {service_nom}
Date : {date_rdv}
Heure : {heure_rdv}
-------------------------------------------

Information financiere :
- Montant total : {total_prix}
- Acompte recu : 10 000 ariary
- Solde a regler sur place : {solde}
-------------------------------------------

Nous vous remercions de votre confiance et restons a votre disposition pour toute information complementaire.

Cordialement,
La Direction
Lalilalou
Contact : +261 34 64 165 66"""
                    
                    if send_gmail_api(client_email, subject_c, body_c):
                        sheet.update_cell(i + 1, 15, "OUI")

                # --- 2. EMAIL DE RAPPEL J-1 ---
                if statut == "CONFIRMÉ" and date_rdv == demain_str and rappel_fait != "OUI":
                    subject_r = f"Notification de rappel : Votre rendez-vous du {date_rdv}"
                    body_r = f"""Bonjour {client_nom},

Ceci est un message automatique pour vous rappeler votre rendez-vous prevu demain au sein de notre établissement Lalilalou.

Recapitulatif logistique :
-------------------------------------------
Date : {date_rdv}
Heure : {heure_rdv}
Service : {service_nom}
-------------------------------------------
Solde a regler sur place : {solde}
-------------------------------------------

En cas d'empechement, nous vous prions de bien vouloir nous en informer dans les plus brefs delais au +261 34 64 165 66.

Dans l'attente de vous recevoir.

Cordialement,
Le Service Clientele
Lalilalou"""
                    
                    if send_gmail_api(client_email, subject_r, body_r):
                        sheet.update_cell(i + 1, 13, "OUI")

    except Exception as e:
        print(f"Erreur Scheduler : {e}")

# --- INITIALISATION DU PLANIFICATEUR ---
job_defaults = {
    'coalesce': True,
    'max_instances': 1
}
scheduler = BackgroundScheduler(daemon=True, job_defaults=job_defaults)
scheduler.add_job(func=trigger_auto_tasks, trigger="interval", minutes=15)
scheduler.add_job(func=archive_old_records, trigger="cron", hour=3, minute=0)
scheduler.start()

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/get-slots', methods=['GET'])
def get_slots():
    try:
        target_date = request.args.get('date')
        sheet = get_google_sheet()
        all_rows = sheet.get_all_values()
        booked = [row[8] for row in all_rows if len(row) > 8 and row[7] == target_date]
        return jsonify(booked)
    except: return jsonify([]), 500

@app.route('/api/book', methods=['POST'])
def book():
    try:
        data = request.json
        sheet = get_google_sheet()
        ref_code = "LL-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        total_prix = f"{data['price']} ariary"
        solde = get_balance(total_prix)

        new_row = [
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
            data['fullname'], data['email'], data['phone'],
            data['category'], data['service'], data['employee'],
            data['date'], data['time'], total_prix,
            data['payment_method'], "EN ATTENTE", "NON", ref_code, "NON"
        ]
        sheet.append_row(new_row)

        # EMAIL ACCUSÉ DE RÉCEPTION (Demande d'acompte)
        subject_c = f"Accuse de reception : Demande de reservation {ref_code}"
        body_c = f"""Bonjour {data['fullname']},

Nous accusons reception de votre demande de reservation effectuee sur notre site internet.

Afin de valider votre creneau horaire, le reglement d'un acompte est requis.

Synthese de la demande :
-------------------------------------------
Reference : {ref_code}
Service : {data['service']}
Date souhaitee : {data['date']}
Heure souhaitee : {data['time']}
-------------------------------------------
Tarif total : {total_prix}
Acompte a regler : 10 000 ariary
Solde restant (le jour du rendez-vous) : {solde}
-------------------------------------------

Instructions de paiement :
Le transfert de l'acompte doit etre effectue via Mvola au numero suivant : +261 34 64 165 66.
Veuillez preciser la reference "{ref_code}" dans le motif du transfert.

Votre dossier sera traite et confirme des reception de ce depot.

Cordialement,
Le Service Clientele
Lalilalou"""
        
        send_gmail_api(data['email'], subject_c, body_c)

        # Notification Admin
        admin_subject = f"Notification : Nouvelle demande de reservation - {ref_code}"
        admin_body = f"""Information relative a une nouvelle demande de reservation :

Identite du client :
- Nom complet : {data['fullname']}
- Telephone : {data['phone']}
- Email : {data['email']}

Details de la prestation :
- Service : {data['service']}
- Date : {data['date']} a {data['time']}
- Reference de dossier : {ref_code}

Statut actuel : En attente de depot."""
        send_gmail_api(MAIL_USER, admin_subject, admin_body)

        return jsonify({"status": "success", "ref": ref_code}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/force-archive')
def force_archive():
    try:
        archive_old_records()
        return "Operation d'archivage effectuee."
    except Exception as e:
        return f"Erreur : {str(e)}"
    
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)