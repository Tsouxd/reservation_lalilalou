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
    print(f"[{datetime.now()}] DÉBUT DE L'ARCHIVAGE...")
    try:
        sheet_main = get_google_sheet()
        sheet_archive = get_google_sheet("Archives")
        
        all_rows = sheet_main.get_all_values()
        limite_date = datetime.now() - timedelta(days=30)
        
        rows_to_move = []
        indices_to_delete = []

        # 1. Identifier les lignes
        for i, row in enumerate(all_rows):
            if i == 0: continue # Sauter l'entête
            
            if len(row) > 7 and row[7]:
                try:
                    # Conversion de la date YYYY-MM-DD
                    date_rdv = datetime.strptime(row[7].strip(), "%Y-%m-%d")
                    
                    if date_rdv < limite_date:
                        rows_to_move.append(row)
                        indices_to_delete.append(i + 1)
                except Exception:
                    continue

        if not rows_to_move:
            print("Aucune donnée ancienne à archiver.")
            return "Rien à archiver"

        # 2. Copier vers l'onglet Archives
        print(f"Copie de {len(rows_to_move)} lignes vers Archives...")
        sheet_archive.append_rows(rows_to_move)

        # 3. Supprimer du sheet principal
        # On trie à l'envers pour ne pas décaler les index
        indices_to_delete.sort(reverse=True)
        
        print(f"Suppression de {len(indices_to_delete)} lignes du sheet principal...")
        for idx in indices_to_delete:
            # CORRECTION ICI : on utilise delete_rows(index)
            sheet_main.delete_rows(idx)
            print(f"Ligne {idx} supprimée.")

        print("--- ARCHIVAGE TERMINÉ AVEC SUCCÈS ---")
        return f"{len(rows_to_move)} lignes déplacées et supprimées"

    except Exception as e:
        print(f"ERREUR CRITIQUE ARCHIVAGE: {e}")
        return f"Erreur: {str(e)}"
    
# --- LOGIQUE DE TRAITEMENT AUTOMATIQUE (Confirmations & Rappels) ---
def trigger_auto_tasks():
    print(f"[{datetime.now()}] Scan du planning pour rappels et confirmations...")
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
                    subject_c = f"Réservation Confirmée ✅ - Réf: {ref_code}"
                    body_c = f"""Bonjour {client_nom},

Nous avons le plaisir de vous informer que votre acompte de 10 000 ariary a bien été reçu. Votre réservation chez Lalilalou Beauty & Spa est désormais officiellement CONFIRMÉE.

RÉCAPITULATIF DE VOTRE SÉANCE :
-------------------------------------------
✨ Référence : {ref_code}
💆 Prestation : {service_nom}
📅 Date : {date_rdv}
🕙 Heure : {heure_rdv}
-------------------------------------------

DÉTAILS FINANCIERS :
💰 Montant total : {total_prix}
✅ Acompte versé : 10 000 ariary
💵 Solde à régler sur place : {solde}
-------------------------------------------

Nous avons hâte de vous accueillir pour ce moment privilégié de soin.

Cordialement,
L'équipe Lalilalou Beauty & Spa
Contact : +261 34 64 165 66"""
                    
                    if send_gmail_api(client_email, subject_c, body_c):
                        sheet.update_cell(i + 1, 15, "OUI")

                # --- 2. EMAIL DE RAPPEL J-1 ---
                if statut == "CONFIRMÉ" and date_rdv == demain_str and rappel_fait != "OUI":
                    subject_r = f"Rappel : Votre rendez-vous de DEMAIN chez Lalilalou 🌸"
                    body_r = f"""Bonjour {client_nom},

C'est un petit message pour vous rappeler votre rendez-vous de DEMAIN chez Lalilalou Beauty & Spa. Nous préparons tout pour votre accueil !

VOTRE RENDEZ-VOUS :
-------------------------------------------
📅 Date : {date_rdv} (DEMAIN)
🕙 Heure : {heure_rdv}
✨ Service : {service_nom}
-------------------------------------------
💵 Solde à prévoir sur place : {solde}
-------------------------------------------

En cas d'empêchement, merci de nous contacter au +261 34 64 165 66 le plus tôt possible.

À demain pour votre moment d'exception !

L'équipe Lalilalou"""
                    
                    if send_gmail_api(client_email, subject_r, body_r):
                        sheet.update_cell(i + 1, 13, "OUI")

    except Exception as e:
        print(f"ERREUR Scheduler Tâches: {e}")

# --- INITIALISATION DU PLANIFICATEUR ---
# On ajoute coalesce et max_instances pour éviter les crashs si Google est lent
job_defaults = {
    'coalesce': True,
    'max_instances': 1
}
scheduler = BackgroundScheduler(daemon=True, job_defaults=job_defaults)

# Scan des emails toutes les 2 minutes (sécurisé pour l'API Google)
scheduler.add_job(func=trigger_auto_tasks, trigger="interval", minutes=15)
# Archivage tous les jours à 3h du matin
scheduler.add_job(func=archive_old_records, trigger="cron", hour=3, minute=0)

# Tâche 2 : Archivage automatique (CHANGÉ : toutes les 2 minutes)
# scheduler.add_job(func=archive_old_records, trigger="interval", minutes=2)

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

        subject_c = f"Demande de réservation {ref_code} - Lalilalou Beauty & Spa 🌸"
        body_c = f"""Bonjour {data['fullname']},

Nous avons bien reçu votre demande de réservation et nous vous remercions de votre confiance.

⚠️ POUR VALIDER DÉFINITIVEMENT VOTRE CRÉNEAU :
Un acompte de 10 000 ariary est nécessaire.

DÉTAILS FINANCIERS :
-------------------------------------------
✨ Référence : {ref_code}
💆 Service : {data['service']}
📅 Date : {data['date']}
🕙 Heure : {data['time']}
-------------------------------------------
💰 Tarif total : {total_prix}
💳 ACOMPTE À RÉGLER (Mvola) : 10 000 ariary
💵 Solde restant (le jour J) : {solde}
-------------------------------------------

MODALITÉS DE PAIEMENT :
Merci d'effectuer le transfert de 10 000 ariary au +261 34 64 165 66.
⚠️ IMPORTANT : Veuillez indiquer la référence "{ref_code}" dans le motif du transfert.

Votre réservation sera confirmée par e-mail dès réception de votre dépôt.

Cordialement,
L'équipe Lalilalou Beauty & Spa
Contact : +261 34 64 165 66"""
        
        send_gmail_api(data['email'], subject_c, body_c)
        send_gmail_api(MAIL_USER, f"🚨 NOUVELLE RÉSA : {ref_code} - {data['fullname']}", f"Demande de {data['fullname']} pour {data['service']}")

        return jsonify({"status": "success", "ref": ref_code}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- ROUTE DE TEST TEMPORAIRE POUR L'ARCHIVAGE ---
@app.route('/force-archive')
def force_archive():
    try:
        archive_old_records()
        return "Opération d'archivage lancée ! Vérifiez vos logs et votre onglet Archives."
    except Exception as e:
        return f"Erreur lors de l'archivage : {str(e)}"
    
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)