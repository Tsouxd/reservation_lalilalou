import os
import json
import base64
from datetime import datetime
from email.mime.text import MIMEText
from flask import Flask, render_template, request, jsonify
import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

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
        if 'private_key' in creds_dict: creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    return gspread.authorize(creds).open("suivi_reservation_lalilalou").sheet1

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
        
        # 1. Enregistrement Sheet
        new_row = [
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
            data['fullname'], data['email'], data['phone'],
            data['category'], data['service'], data['employee'],
            data['date'], data['time'], f"{data['price']}€",
            data['payment_method'], "EN ATTENTE"
        ]
        sheet.append_row(new_row)

        payment_label = "Sur place" if data['payment_method'] == "sur_place" else "Mobile Money (Mvola)"

        # 2. Email Client : Style Professionnel
        subject_c = f"Demande de réservation reçue - Lalilalou Beauty & Spa 🌸"
        body_c = f"""Bonjour {data['fullname']},

Nous vous remercions d'avoir choisi Lalilalou Beauty & Spa. 

Votre demande de réservation pour le service "{data['service']}" a bien été enregistrée.

DÉTAILS DE VOTRE RÉSERVATION :
-------------------------------------------
📅 Date : {data['date']}
🕙 Heure : {data['time']}
👤 Praticien : {data['employee']}
💰 Tarif : {data['price']}€
💳 Mode de paiement : {payment_label}
-------------------------------------------

STATUT : EN ATTENTE DE VALIDATION
Votre réservation n'est pas encore définitive. Notre équipe vérifie actuellement nos disponibilités. Vous recevrez un e-mail de confirmation finale ou un appel de notre part très prochainement.

{"⚠️ RAPPEL MVOLA : Pour garantir votre créneau, merci d'effectuer le transfert au +261 34 64 165 66. Votre demande sera traitée dès réception du dépôt." if data['payment_method'] == 'mvola' else ""}

Merci de votre confiance et à très bientôt pour votre moment de bien-être.

Cordialement,

L'équipe Lalilalou
Contact : +261 34 64 165 66
"""
        send_gmail_api(data['email'], subject_c, body_c)

        # 3. Email Admin : Détails complets du client
        subject_a = f"🚨 NOUVELLE DEMANDE : {data['fullname']} ({data['service']})"
        body_a = f"""Bonjour admin,

Une nouvelle demande de réservation vient d'être effectuée sur le site.

COORDONNÉES DU CLIENT :
-------------------------------------------
👤 Nom complet : {data['fullname']}
📧 Email : {data['email']}
📞 Téléphone : {data['phone']}

DÉTAILS DE LA PRESTATION :
-------------------------------------------
✨ Service : {data['service']} ({data['category']})
📅 Date : {data['date']}
🕙 Heure : {data['time']}
👤 Employé : {data['employee']}
💰 Prix : {data['price']}€
💳 Paiement : {payment_label}

ACTION REQUISE :
Veuillez vérifier le planning et valider ou refuser cette demande dans votre Google Sheet de suivi.
"""
        send_gmail_api(MAIL_USER, subject_a, body_a)

        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)