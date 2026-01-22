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

# --- CONFIGURATION ---
GMAIL_CLIENT_ID = os.environ.get('GMAIL_CLIENT_ID')
GMAIL_CLIENT_SECRET = os.environ.get('GMAIL_CLIENT_SECRET')
GMAIL_REFRESH_TOKEN = os.environ.get('GMAIL_REFRESH_TOKEN')
MAIL_USER = os.environ.get('MAIL_USER', 'tsourakotoson0@gmail.com')
WEBHOOK_SECRET = "Lalilalou1234"

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

def get_balance(total_str):
    try:
        total = int(''.join(filter(str.isdigit, total_str)))
        return f"{total - 10000} ariary"
    except:
        return "à calculer"

# --- LOGIQUE COMMUNE POUR L'EMAIL DE CONFIRMATION ---
def send_confirmation_email(client_nom, client_email, service_nom, date_rdv, heure_rdv, total_prix, ref_code):
    solde = get_balance(total_prix)
    subject = f"Confirmation de votre réservation ✅ - Réf: {ref_code}"
    body = f"""Bonjour {client_nom},

C'est avec plaisir que nous vous confirmons la réception de votre acompte. Votre rendez-vous chez Lalilalou Beauty & Spa est désormais officiellement bloqué dans notre planning.

VOTRE RÉCAPITULATIF FINAL :
-------------------------------------------
✨ Référence : {ref_code}
💆 Prestation : {service_nom}
📅 Date : {date_rdv}
🕙 Heure : {heure_rdv}
-------------------------------------------

DÉTAILS FINANCIERS :
💰 Tarif total de la prestation : {total_prix}
✅ Acompte reçu : 10 000 ariary
💵 Reste à régler sur place : {solde}
-------------------------------------------

Nous préparons tout pour vous offrir un moment d'exception et de détente. 

Au plaisir de vous recevoir très bientôt,

L'équipe Lalilalou Beauty & Spa
Contact : +261 34 64 165 66"""
    return send_gmail_api(client_email, subject, body)

# --- ROUTE WEBHOOK (POUR ENVOI INSTANTANÉ) ---
@app.route('/api/webhook/confirm', methods=['POST'])
def webhook_confirm():
    token = request.args.get('token')
    if token != WEBHOOK_SECRET:
        return jsonify({"status": "unauthorized"}), 403
    try:
        data = request.json
        row_index = data.get('row')
        sheet = get_google_sheet()
        row_data = sheet.row_values(row_index)

        if len(row_data) >= 12:
            statut = row_data[11].strip().upper()
            confirm_faite = row_data[14].upper() if len(row_data) > 14 else "NON"

            if statut == "CONFIRMÉ" and confirm_faite != "OUI":
                if send_confirmation_email(row_data[1], row_data[2], row_data[5], row_data[7], row_data[8], row_data[9], row_data[13]):
                    sheet.update_cell(row_index, 15, "OUI")
                    return jsonify({"status": "success"}), 200
        return jsonify({"status": "no_action"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- LOGIQUE SCHEDULER (SÉCURITÉ & RAPPEL J-1) ---
def trigger_auto_tasks():
    try:
        sheet = get_google_sheet()
        all_rows = sheet.get_all_values()
        demain_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        for i, row in enumerate(all_rows):
            if i == 0: continue 
            if len(row) >= 12:
                statut = row[11].strip().upper()
                confirm_faite = row[14].upper() if len(row) > 14 else "NON"
                
                # Fallback Confirmation
                if statut == "CONFIRMÉ" and confirm_faite != "OUI":
                    if send_confirmation_email(row[1], row[2], row[5], row[7], row[8], row[9], row[13]):
                        sheet.update_cell(i + 1, 15, "OUI")

                # Rappel J-1
                rappel_fait = row[12].upper() if len(row) > 12 else "NON"
                if statut == "CONFIRMÉ" and row[7] == demain_str and rappel_fait != "OUI":
                    client_nom = row[1]
                    solde = get_balance(row[9])
                    subject_r = f"Rappel : Votre moment de bien-être DEMAIN chez Lalilalou 🌸"
                    body_r = f"""Bonjour {client_nom},

Nous trépignons d'impatience à l'idée de vous accueillir demain pour votre séance chez Lalilalou Beauty & Spa.

VOTRE RENDEZ-VOUS DE DEMAIN :
-------------------------------------------
📅 Date : {row[7]} (DEMAIN)
🕙 Heure : {row[8]}
💆 Prestation : {row[5]}
-------------------------------------------
💵 Solde restant à prévoir : {solde}
-------------------------------------------

Merci de votre ponctualité pour profiter pleinement de votre soin. En cas d'empêchement, merci de nous prévenir au plus vite au +261 34 64 165 66.

À demain pour votre parenthèse de douceur !

L'équipe Lalilalou"""
                    if send_gmail_api(row[2], subject_r, body_r):
                        sheet.update_cell(i + 1, 13, "OUI")
    except Exception as e:
        print(f"Erreur Scheduler: {e}")

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(func=trigger_auto_tasks, trigger="interval", minutes=15)
scheduler.start()

# --- ROUTES CLASSIQUES ---
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

        # EMAIL ACCUSÉ DE RÉCEPTION
        subject_c = f"Demande de réservation {ref_code} - Lalilalou Beauty & Spa 🌸"
        body_c = f"""Bonjour {data['fullname']},

Nous avons bien reçu votre demande de réservation et nous vous remercions de votre confiance. 

⚠️ ACTION REQUISE POUR VALIDER VOTRE CRÉNEAU :
Votre réservation est actuellement en attente. Un acompte est indispensable pour confirmer définitivement votre place dans notre planning.

RÉSUMÉ DE VOTRE DEMANDE :
-------------------------------------------
✨ Référence : {ref_code}
💆 Prestation : {data['service']}
📅 Date : {data['date']}
🕙 Heure : {data['time']}
-------------------------------------------
💰 Tarif total : {total_prix}
💳 ACOMPTE À RÉGLER (Mvola) : 10 000 ariary
💵 Solde restant (le jour J) : {solde}
-------------------------------------------

COMMENT RÉGLER VOTRE ACOMPTE ?
Veuillez effectuer le transfert de 10 000 ariary au numéro suivant :
📞 Mvola : +261 34 64 165 66
⚠️ IMPORTANT : Mentionnez impérativement la référence "{ref_code}" dans le motif du transfert.

Dès réception de votre dépôt, vous recevrez un e-mail de confirmation finale.

À très bientôt pour votre moment de beauté,

L'équipe Lalilalou Beauty & Spa
Contact : +261 34 64 165 66"""
        
        send_gmail_api(data['email'], subject_c, body_c)
        
        # Admin Alert
        admin_body = f"Nouvelle demande : {data['fullname']} ({data['phone']}) - Service: {data['service']} - Réf: {ref_code}"
        send_gmail_api(MAIL_USER, f"🚨 NOUVELLE RÉSA : {ref_code}", admin_body)

        return jsonify({"status": "success", "ref": ref_code}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)