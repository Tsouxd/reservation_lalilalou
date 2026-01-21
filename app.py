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

# Planificateur de tâches
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()
app = Flask(__name__)

# --- CONFIGURATION GMAIL API ---
GMAIL_CLIENT_ID = os.environ.get('GMAIL_CLIENT_ID')
GMAIL_CLIENT_SECRET = os.environ.get('GMAIL_CLIENT_SECRET')
GMAIL_REFRESH_TOKEN = os.environ.get('GMAIL_REFRESH_TOKEN')
MAIL_USER = os.environ.get('MAIL_USER', 'tsourakotoson0@gmail.com')

def get_gmail_service():
    creds = Credentials(
        None,
        refresh_token=GMAIL_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GMAIL_CLIENT_ID,
        client_secret=GMAIL_CLIENT_SECRET,
    )
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
def get_google_sheet():
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
    return gspread.authorize(creds).open("suivi_reservation_lalilalou").sheet1

# --- LOGIQUE DE RAPPEL AUTOMATIQUE ---
def trigger_auto_reminders():
    # Print pour le suivi dans les logs de Render
    print(f"[{datetime.now()}] Scan des rappels en cours...")
    try:
        sheet = get_google_sheet()
        all_rows = sheet.get_all_values()
        
        # Demain au format YYYY-MM-DD
        demain_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        envoyes = 0

        for i, row in enumerate(all_rows):
            if i == 0: continue # Skip header

            # Index 7: Date | Index 11: Statut | Index 12: Rappel (M) | Index 13: Réf (N)
            if len(row) >= 12:
                date_rdv = row[7]
                statut = row[11]
                deja_envoye = row[12] if len(row) > 12 else "NON"
                ref_code = row[13] if len(row) > 13 else "N/A"

                if date_rdv == demain_str and "ANNULÉ" not in statut.upper() and deja_envoye != "OUI":
                    client_nom = row[1]
                    client_email = row[2]
                    service_nom = row[5]
                    heure_rdv = row[8]

                    subject = f"Rappel : Votre moment bien-être demain (Réf: {ref_code}) 🌸"
                    body = f"""Bonjour {client_nom},

C'est un petit rappel pour votre rendez-vous de demain chez Lalilalou Beauty & Spa.

DÉTAILS DU RENDEZ-VOUS :
-------------------------------------------
✨ Référence : {ref_code}
✨ Service : {service_nom}
📅 Date : {date_rdv} (Demain)
🕙 Heure : {heure_rdv}
-------------------------------------------

Nous avons hâte de vous recevoir ! En cas d'empêchement, merci de nous prévenir au plus tôt au +261 34 64 165 66.

Cordialement,
L'équipe Lalilalou"""
                    
                    if send_gmail_api(client_email, subject, body):
                        sheet.update_cell(i + 1, 13, "OUI")
                        envoyes += 1

        if envoyes > 0:
            print(f"[{datetime.now()}] INFO: {envoyes} rappel(s) envoyé(s).")
    except Exception as e:
        print(f"ERREUR Scheduler: {e}")

# --- INITIALISATION DU PLANIFICATEUR ---
# On utilise daemon=True pour que le thread s'arrête proprement avec l'app
scheduler = BackgroundScheduler(daemon=True)
# On vérifie toutes les 60 minutes
scheduler.add_job(func=trigger_auto_reminders, trigger="interval", minutes=60)
scheduler.start()

# --- ROUTES ---
@app.route('/')
def index():
    # Sur serveur payant, inutile de trigger ici car le scheduler tourne 24h/24
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
        
        # Génération Référence
        chars = string.ascii_uppercase + string.digits
        ref_code = "LL-" + ''.join(random.choices(chars, k=5))

        # Enregistrement (14 colonnes)
        new_row = [
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
            data['fullname'], data['email'], data['phone'],
            data['category'], data['service'], data['employee'],
            data['date'], data['time'], f"{data['price']} ariary",
            data['payment_method'], "EN ATTENTE",
            "NON",    # M: Rappel Envoyé
            ref_code  # N: Référence
        ]
        sheet.append_row(new_row)

        payment_label = "Paiement sur place" if data['payment_method'] == "sur_place" else "Mobile Money (Mvola)"

        # Mail Client
        subject_c = f"Demande de réservation {ref_code} - Lalilalou 🌸"
        body_c = f"""Bonjour {data['fullname']},

Nous avons bien enregistré votre demande sous la référence : {ref_code}

DÉTAILS :
✨ Référence : {ref_code}
📅 Date : {data['date']}
🕙 Heure : {data['time']}
💰 Tarif : {data['price']} ariary
💳 Paiement : {payment_label}

STATUT : EN ATTENTE DE VALIDATION
Votre réservation sera confirmée après vérification du planning.

{"⚠️ INSTRUCTIONS MVOLA : Merci d'effectuer le transfert au +261 34 64 165 66. Indiquez la référence " + ref_code + " dans le motif du transfert." if data['payment_method'] == 'mvola' else ""}

Cordialement,
L'équipe Lalilalou"""
        send_gmail_api(data['email'], subject_c, body_c)

        # Mail Admin
        subject_a = f"🚨 NOUVELLE RÉSA : {ref_code} - {data['fullname']}"
        body_a = f"Référence : {ref_code}\nClient : {data['fullname']}\nTel : {data['phone']}\nService : {data['service']}\nDate : {data['date']} à {data['time']}\nPaiement : {payment_label}"
        send_gmail_api(MAIL_USER, subject_a, body_a)

        return jsonify({"status": "success", "ref": ref_code}), 200
    except Exception as e:
        print(f"Erreur booking: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    
if __name__ == '__main__':
    # Sur Render, le port est injecté via la variable d'env PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)