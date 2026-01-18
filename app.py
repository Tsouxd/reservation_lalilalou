import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_mail import Mail, Message
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# Charger le fichier .env
load_dotenv()

app = Flask(__name__)

# ─────────────────────────────────────────────
# Configuration EMAIL (SSL Port 465)
# ─────────────────────────────────────────────
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 465))
app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL') == 'True'
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USER')

# Nettoyage automatique du mot de passe
raw_pass = os.environ.get('MAIL_PASS', '')
app.config['MAIL_PASSWORD'] = raw_pass.replace(" ", "")

app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')

mail = Mail(app)
ADMIN_EMAIL = app.config['MAIL_USERNAME']

# ─────────────────────────────────────────────
# Google Sheets (Priorité à la Variable d'ENV)
# ─────────────────────────────────────────────
def get_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # On récupère la variable GOOGLE_CREDS
    creds_json = os.environ.get("GOOGLE_CREDS")

    if creds_json:
        try:
            # Nettoyage au cas où la variable est entourée de guillemets simples dans le .env
            if creds_json.startswith("'") and creds_json.endswith("'"):
                creds_json = creds_json[1:-1]
            
            creds_dict = json.loads(creds_json)
            
            # Correction cruciale pour la clé privée
            if 'private_key' in creds_dict:
                creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            print("INFO: Connexion Google Sheets via ENV réussie.")
        except Exception as e:
            print(f"ERREUR: Problème avec GOOGLE_CREDS dans l'ENV : {e}")
            return None
    else:
        # Fallback local (pourra être supprimé plus tard)
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
            print("INFO: Connexion Google Sheets via credentials.json réussie.")
        except Exception as e:
            print(f"ERREUR: Aucun identifiant Google trouvé (ENV ou fichier) : {e}")
            return None

    try:
        client = gspread.authorize(creds)
        return client.open("suivi_reservation_lalilalou").sheet1
    except Exception as e:
        print(f"ERREUR d'autorisation Google Sheets : {e}")
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

        # 1. Enregistrement
        new_row = [
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
            data['fullname'], data['email'], data['phone'],
            data['category'], data['service'], data['employee'],
            data['date'], data['time'], f"{data['price']}€",
            data['payment_method'], "EN ATTENTE"
        ]
        sheet.append_row(new_row)

        payment_label = "Paiement sur place" if data['payment_method'] == "sur_place" else "Mobile Money (Mvola)"

        # 2. Préparation Mail Client
        client_msg = Message(
            subject=f"Accusé de réception : Votre demande chez Lalilalou 🌸",
            recipients=[data['email']]
        )
        client_msg.body = f"Bonjour {data['fullname']},\n\nNous avons bien reçu votre demande pour {data['service']} le {data['date']} à {data['time']}.\nVotre réservation est actuellement EN ATTENTE DE VALIDATION.\n\nCordialement,\nL'équipe Lalilalou"

        # 3. Préparation Mail Admin
        admin_msg = Message(
            subject=f"🚨 NOUVELLE RÉSERVATION : {data['fullname']}",
            recipients=[ADMIN_EMAIL]
        )
        admin_msg.body = f"Nouvelle demande :\nClient: {data['fullname']}\nTel: {data['phone']}\nService: {data['service']}\nDate: {data['date']} à {data['time']}\nPaiement: {payment_label}"

        # 4. Envoi
        with mail.connect() as conn:
            conn.send(client_msg)
            conn.send(admin_msg)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"Erreur réservation: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)