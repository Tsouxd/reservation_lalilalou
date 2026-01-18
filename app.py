import os
import json
from flask import Flask, render_template, request, jsonify
from flask_mail import Mail, Message
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

app = Flask(__name__)

# --- Configuration Email ---
# En local, il utilisera vos identifiants fournis. 
# Sur Render, il cherchera les variables MAIL_USER et MAIL_PASS.
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USER', 'tsourakotoson0@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASS', 'tvts gvaq urbm ueht') 
mail = Mail(app)

# Email de l'admin
ADMIN_EMAIL = os.environ.get('MAIL_USER', 'tsourakotoson0@gmail.com')

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
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        
    client = gspread.authorize(creds)
    return client.open("suivi_reservation_lalilalou").sheet1

@app.route('/api/get-slots', methods=['GET'])
def get_slots():
    try:
        target_date = request.args.get('date')
        sheet = get_google_sheet()
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
        
        # 1. Enregistrement
        new_row = [
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
            data['fullname'], data['email'], data['phone'],
            data['category'], data['service'], data['employee'],
            data['date'], data['time'], f"{data['price']}€",
            data['payment_method'], "EN ATTENTE"
        ]
        sheet.append_row(new_row)

        payment_method_label = "Paiement sur place" if data['payment_method'] == "sur_place" else "Mobile Money (Mvola)"

        # 2. EMAIL CLIENT : Professionnel et rassurant
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
        mail.send(client_msg)

        # 3. EMAIL ADMIN : Efficace et direct
        admin_msg = Message(
            subject=f"🚨 NOUVELLE DEMANDE : {data['fullname']} - {data['service']}",
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
        mail.send(admin_msg)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({"status": "error", "message": "Une erreur technique est survenue"}), 500
    
if __name__ == '__main__':
    # Configuration pour le port de Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)