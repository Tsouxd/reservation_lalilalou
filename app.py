import os
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# Charger le fichier .env
load_dotenv()

app = Flask(__name__)

# ─────────────────────────────────────────────
# Configuration EMAIL (Lecture directe du .env)
# ─────────────────────────────────────────────
MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
MAIL_PORT = int(os.environ.get('MAIL_PORT', 465))
MAIL_USER = os.environ.get('MAIL_USER')
# Nettoyage automatique du mot de passe
raw_pass = os.environ.get('MAIL_PASS', '')
MAIL_PASS = raw_pass.replace(" ", "")

# Expéditeur par défaut (Format: Nom <email@gmail.com>)
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', MAIL_USER)
ADMIN_EMAIL = MAIL_USER

# ─────────────────────────────────────────────
# Google Sheets (Priorité à GOOGLE_CREDS)
# ─────────────────────────────────────────────
def get_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GOOGLE_CREDS")

    if creds_json:
        try:
            # Nettoyage des guillemets simples si présents
            if creds_json.startswith("'") and creds_json.endswith("'"):
                creds_json = creds_json[1:-1]
            
            creds_dict = json.loads(creds_json)
            
            # Correction cruciale pour la clé privée (gestion des \n)
            if 'private_key' in creds_dict:
                creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        except Exception as e:
            print(f"ERREUR GOOGLE_CREDS: {e}")
            return None
    else:
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        except Exception as e:
            print(f"ERREUR Fichier Local: {e}")
            return None

    try:
        client = gspread.authorize(creds)
        return client.open("suivi_reservation_lalilalou").sheet1
    except Exception as e:
        print(f"ERREUR Google Auth: {e}")
        return None

# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/get-slots', methods=['GET'])
def get_slots():
    try:
        target_date = request.args.get('date')
        sheet = get_google_sheet()
        if not sheet: return jsonify([]), 500
        
        all_rows = sheet.get_all_values()
        booked_slots = []
        for row in all_rows:
            if len(row) > 8 and row[7] == target_date:
                booked_slots.append(row[8])
        return jsonify(booked_slots)
    except Exception as e:
        print(f"Erreur get-slots: {e}")
        return jsonify([]), 500

@app.route('/api/book', methods=['POST'])
def book():
    try:
        data = request.json
        sheet = get_google_sheet()
        if not sheet: raise Exception("Sheet inaccessible")

        # 1. Enregistrement Google Sheets
        new_row = [
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
            data['fullname'], data['email'], data['phone'],
            data['category'], data['service'], data['employee'],
            data['date'], data['time'], f"{data['price']}€",
            data['payment_method'], "EN ATTENTE"
        ]
        sheet.append_row(new_row)

        payment_label = "Paiement sur place" if data['payment_method'] == "sur_place" else "Mobile Money (Mvola)"

        # 2. Préparation des messages
        subject_client = "Accusé de réception : Votre demande chez Lalilalou 🌸"
        body_client = f"Bonjour {data['fullname']},\n\nNous avons bien reçu votre demande pour {data['service']} le {data['date']} à {data['time']}.\nVotre réservation est actuellement EN ATTENTE DE VALIDATION.\n\nCordialement,\nL'équipe Lalilalou"

        subject_admin = f"🚨 NOUVELLE RÉSERVATION : {data['fullname']}"
        body_admin = f"Nouvelle demande :\nClient: {data['fullname']}\nTel: {data['phone']}\nService: {data['service']}\nDate: {data['date']} à {data['time']}\nPaiement: {payment_label}"

        # 3. Envoi via smtplib (Utilise les variables MAIL_SERVER et MAIL_PORT)
        try:
            # On utilise SMTP_SSL car ton port est 465
            with smtplib.SMTP_SSL(MAIL_SERVER, MAIL_PORT) as server:
                server.login(MAIL_USER, MAIL_PASS)
                
                # Mail Client
                msg_c = MIMEMultipart()
                msg_c['From'] = MAIL_DEFAULT_SENDER
                msg_c['To'] = data['email']
                msg_c['Subject'] = subject_client
                msg_c.attach(MIMEText(body_client, 'plain'))
                server.send_message(msg_c)

                # Mail Admin
                msg_a = MIMEMultipart()
                msg_a['From'] = MAIL_DEFAULT_SENDER
                msg_a['To'] = ADMIN_EMAIL
                msg_a['Subject'] = subject_admin
                msg_a.attach(MIMEText(body_admin, 'plain'))
                server.send_message(msg_a)
                
            print("Succès: Emails envoyés via SMTP_SSL")
        except Exception as e_mail:
            print(f"Avertissement: Erreur envoi mail ({e_mail}) mais Sheet mis à jour.")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"Erreur réservation: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)