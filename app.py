import os
import json
import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from flask import Flask, render_template, request, jsonify
import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import string
import random

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

# --- LOGIQUE DE RAPPEL AUTOMATIQUE (Colonne M intégrée) ---
def trigger_auto_reminders():
    try:
        sheet = get_google_sheet()
        all_rows = sheet.get_all_values()
        
        # Date de demain au format YYYY-MM-DD (correspondant à votre format Sheet)
        demain_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        envoyes = 0

        # enumerate(all_rows) permet de suivre le numéro de ligne pour la mise à jour
        # On commence à l'index 1 (deuxième ligne du sheet)
        for i, row in enumerate(all_rows):
            if i == 0: continue # Sauter l'en-tête

            # Index 7: Date RDV | Index 11: Statut | Index 12: Rappel Envoyé (Colonne M)
            if len(row) >= 12:
                date_rdv = row[7]
                statut = row[11]
                # Si la colonne M n'existe pas encore sur la ligne, on considère "NON"
                deja_envoye = row[12] if len(row) > 12 else "NON"

                # Condition : C'est demain ET ce n'est pas annulé ET pas encore envoyé
                if date_rdv == demain_str and "ANNULÉ" not in statut.upper() and deja_envoye != "OUI":
                    client_nom = row[1]
                    client_email = row[2]
                    service_nom = row[5]
                    heure_rdv = row[8]

                    subject = f"Rappel : Votre moment bien-être demain chez Lalilalou 🌸"
                    body = f"""Bonjour {client_nom},

C'est un petit rappel pour votre rendez-vous de demain chez Lalilalou Beauty & Spa.

DÉTAILS DU RENDEZ-VOUS :
-------------------------------------------
✨ Service : {service_nom}
📅 Date : {date_rdv} (Demain)
🕙 Heure : {heure_rdv}
-------------------------------------------

Nous avons hâte de vous recevoir ! En cas d'empêchement, merci de nous prévenir au plus tôt.

Cordialement,
L'équipe Lalilalou
Contact : +261 34 64 165 66"""
                    
                    if send_gmail_api(client_email, subject, body):
                        # Mise à jour de la colonne M (13ème colonne) pour cette ligne spécifique
                        # i + 1 car l'index de liste commence à 0 et le sheet à 1
                        sheet.update_cell(i + 1, 13, "OUI")
                        envoyes += 1

        if envoyes > 0:
            print(f"INFO: {envoyes} rappel(s) envoyé(s) pour le {demain_str}")

    except Exception as e:
        print(f"Erreur Rappels Automatiques: {e}")

# --- ROUTES ---
@app.route('/')
def index():
    # Déclenché par UptimeRobot
    trigger_auto_reminders()
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
        
        # --- GÉNÉRATION DE LA RÉFÉRENCE UNIQUE ---
        # Crée une chaine comme LL-A739B
        chars = string.ascii_uppercase + string.digits
        ref_code = "LL-" + ''.join(random.choices(chars, k=5))

        # 1. Enregistrement Sheet (On ajoute la réf en 14ème colonne)
        new_row = [
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
            data['fullname'], data['email'], data['phone'],
            data['category'], data['service'], data['employee'],
            data['date'], data['time'], f"{data['price']}ariary",
            data['payment_method'], "EN ATTENTE",
            "NON",    # Rappel Envoyé (Colonne M)
            ref_code  # Référence Paiement (Colonne N)
        ]
        sheet.append_row(new_row)

        payment_label = "Sur place" if data['payment_method'] == "sur_place" else "Mobile Money (Mvola)"

        # 2. Email Client : Style Professionnel avec Référence
        subject_c = f"Demande de réservation {ref_code} - Lalilalou 🌸"
        body_c = f"""Bonjour {data['fullname']},

Nous avons bien enregistré votre demande de réservation sous la référence : {ref_code}

DÉTAILS DE VOTRE RÉSERVATION :
-------------------------------------------
✨ Référence : {ref_code}
📅 Date : {data['date']}
🕙 Heure : {data['time']}
💰 Tarif : {data['price']}ariary
💳 Paiement : {payment_label}
-------------------------------------------

STATUT : EN ATTENTE DE VALIDATION
Votre réservation sera confirmée après vérification de notre planning.

{"⚠️ INSTRUCTIONS MVOLA : Pour valider votre rendez-vous, merci d'effectuer le transfert au +261 34 64 165 66. IMPORTANT : Indiquez la référence " + ref_code + " dans le motif du transfert." if data['payment_method'] == 'mvola' else ""}

Cordialement,
L'équipe Lalilalou
Contact : +261 34 64 165 66
"""
        send_gmail_api(data['email'], subject_c, body_c)

        # 3. Email Admin
        subject_a = f"🚨 NOUVELLE RÉSA : {ref_code} - {data['fullname']}"
        body_a = f"""Une nouvelle réservation a été effectuée.

RÉFÉRENCE : {ref_code}
-------------------------------------------
👤 Client : {data['fullname']}
📧 Email : {data['email']}
📞 Tel : {data['phone']}

DÉTAILS :
✨ Service : {data['service']}
📅 Date : {data['date']} à {data['time']}
💰 Prix : {data['price']}ariary
💳 Paiement : {payment_label}
"""
        send_gmail_api(MAIL_USER, subject_a, body_a)

        return jsonify({"status": "success", "ref": ref_code}), 200
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)