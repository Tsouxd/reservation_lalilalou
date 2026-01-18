import os
import json
from flask import Flask, render_template, request, jsonify
from flask_mail import Mail, Message
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

app = Flask(__name__)

# --- Configuration Email (Optimisée pour Render) ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

# Récupération sécurisée et nettoyage du mot de passe
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USER', 'tsourakotoson0@gmail.com')
raw_password = os.environ.get('MAIL_PASS', 'tvts gvaq urbm ueht')
# On retire les espaces pour éviter les erreurs d'authentification
app.config['MAIL_PASSWORD'] = raw_password.replace(" ", "")

mail = Mail(app)

# Email de l'administrateur
ADMIN_EMAIL = app.config['MAIL_USERNAME']

# --- Configuration Google Sheets ---
def get_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Détection de l'environnement
    google_creds_json = os.environ.get("GOOGLE_CREDS")
    
    if google_creds_json:
        # Configuration pour RENDER
        creds_dict = json.loads(google_creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # Configuration pour LOCAL (utilise le fichier credentials.json)
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        except Exception:
            # Fallback si le fichier est manquant en local
            return None
        
    client = gspread.authorize(creds)
    return client.open("suivi_reservation_lalilalou").sheet1

@app.route('/api/get-slots', methods=['GET'])
def get_slots():
    try:
        target_date = request.args.get('date')
        sheet = get_google_sheet()
        if not sheet: return jsonify([]), 500
        
        all_records = sheet.get_all_values()
        booked_slots = []
        for row in all_records:
            if len(row) > 8:
                row_date = row[7]
                row_time = row[8]
                if row_date == target_date:
                    booked_slots.append(row_time)
        return jsonify(booked_slots)
    except Exception as e:
        print(f"Erreur lors de la récupération des créneaux: {e}")
        return jsonify([]), 500
    
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/book', methods=['POST'])
def book():
    try:
        data = request.json
        sheet = get_google_sheet()
        if not sheet: raise Exception("Impossible d'accéder au Sheet")
        
        # 1. Enregistrement (Action prioritaire)
        new_row = [
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
            data['fullname'], data['email'], data['phone'],
            data['category'], data['service'], data['employee'],
            data['date'], data['time'], f"{data['price']}€",
            data['payment_method'], "EN ATTENTE"
        ]
        sheet.append_row(new_row)

        payment_method_label = "Paiement sur place" if data['payment_method'] == "sur_place" else "Mobile Money (Mvola)"

        # 2. Préparation du message Client
        client_msg = Message(
            subject=f"Accusé de réception : Votre demande chez Lalilalou 🌸",
            sender=("Lalilalou Beauty & Spa", app.config['MAIL_USERNAME']),
            recipients=[data['email']]
        )
        client_msg.body = f"""
Bonjour {data['fullname']},

Nous vous remercions d'avoir choisi Lalilalou pour votre prochain moment de bien-être.

Votre demande de réservation a bien été enregistrée et est actuellement en cours d'examen par notre équipe. 

RECAPITULATIF DE VOTRE DEMANDE :
-------------------------------------------
✨ Service : {data['service']}
📅 Date : {data['date']}
🕙 Heure : {data['time']}
👤 Praticien : {data['employee']}
💰 Montant estimé : {data['price']}€
💳 Mode de règlement : {payment_method_label}
-------------------------------------------

PROCHAINE ÉTAPE :
Notre équipe vérifie nos disponibilités de dernière minute. Vous recevrez un e-mail de confirmation définitive ou un appel de notre part dans les plus brefs délais.

{"⚠️ INFO PAIEMENT MVOLA : Pour garantir votre créneau, merci d'effectuer le transfert au +261 34 64 165 66. Votre réservation sera validée dès réception." if data['payment_method'] == 'mvola' else ""}

Nous avons hâte de vous recevoir pour vous offrir une expérience d'exception.

Cordialement,

L'équipe Lalilalou
Service Clientèle
Contact : +261 34 64 165 66
"""

        # 3. Préparation du message Admin
        admin_msg = Message(
            subject=f"🚨 NOUVELLE DEMANDE : {data['fullname']}",
            sender=("Système Lalilalou", app.config['MAIL_USERNAME']),
            recipients=[ADMIN_EMAIL]
        )
        admin_msg.body = f"""
Une nouvelle demande de réservation vient d'arriver via le site internet.

DÉTAILS DU CLIENT :
- Nom : {data['fullname']}
- Téléphone : {data['phone']}
- Email : {data['email']}

DÉTAILS DU RENDEZ-VOUS :
- Service : {data['service']} ({data['category']})
- Créneau : le {data['date']} à {data['time']}
- Praticien : {data['employee']}
- Prix : {data['price']}€
- Paiement : {payment_method_label}

Lien vers le suivi Google Sheets : https://docs.google.com/spreadsheets/d/1qMl7OXvUzOzHoHCN5rYTmpC1az081a6sx_R-NGEErBI/edit?gid=0#gid=0

Action requise : Contacter le client pour valider le rendez-vous.
"""

        # 4. ENVOI GROUPÉ (Optimisé)
        with mail.connect() as conn:
            conn.send(client_msg)
            conn.send(admin_msg)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"Erreur lors de la réservation: {e}")
        return jsonify({"status": "error", "message": "Une erreur technique est survenue"}), 500
    
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)