from flask import Flask, render_template, request, jsonify
from flask_mail import Mail, Message
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

app = Flask(__name__)

# --- Configuration Email ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'tsourakotoson0@gmail.com'
app.config['MAIL_PASSWORD'] = 'tvts gvaq urbm ueht' 
mail = Mail(app)

# --- Email de l'administrateur (celui qui reçoit les notifications) ---
ADMIN_EMAIL = 'tsourakotoson0@gmail.com' 

# --- Configuration Google Sheets ---
def get_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
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
        
        # 1. Enregistrement dans Google Sheets
        sheet = get_google_sheet()
        new_row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
            data['fullname'],
            data['email'],
            data['phone'],
            data['category'],
            data['service'],
            data['employee'],
            data['date'],
            data['time'],
            f"{data['price']}€",
            data['payment_method'],
            "EN ATTENTE"
        ]
        sheet.append_row(new_row)

        payment_text = "Paiement sur place" if data['payment_method'] == "sur_place" else "Paiement par Mvola (+261 34 64 165 66)"

        # 2. ENVOI DE L'EMAIL AU CLIENT
        client_msg = Message(
            "Demande de réservation reçue - En attente de validation",
            sender=("Lalilalou", app.config['MAIL_USERNAME']),
            recipients=[data['email']]
        )
        client_msg.body = f"""
        Bonjour {data['fullname']},

        Nous avons bien reçu votre demande de réservation.

        IMPORTANT : Votre réservation est actuellement EN ATTENTE DE VALIDATION. 

        Détails de votre demande :
        - Service : {data['service']}
        - Date et Heure : {data['date']} à {data['time']}
        - Mode de paiement choisi : {payment_text}
        - Montant : {data['price']}€

        {"⚠️ Si vous avez choisi Mvola, merci d'effectuer le transfert au +261 34 64 165 66 pour accélérer la validation." if data['payment_method'] == "mvola" else ""}

        À très bientôt,
        L'équipe Lalilalou
        """
        mail.send(client_msg)

        # 3. ENVOI DE L'EMAIL À L'ADMIN (NOTIFICATION)
        admin_msg = Message(
            f"🔔 NOUVELLE RÉSERVATION : {data['fullname']}",
            sender=("Système Réservation", app.config['MAIL_USERNAME']),
            recipients=[ADMIN_EMAIL]
        )
        admin_msg.body = f"""
        Nouvelle demande de réservation à traiter :

        CLIENT :
        - Nom : {data['fullname']}
        - Email : {data['email']}
        - Tel : {data['phone']}

        RÉSERVATION :
        - Service : {data['service']} ({data['category']})
        - Date : {data['date']}
        - Heure : {data['time']}
        - Employé : {data['employee']}
        - Prix : {data['price']}€

        PAIEMENT :
        - Méthode : {data['payment_method']}
        
        Action requise : Vérifiez vos disponibilités et répondez au client pour valider ou refuser.
        """
        mail.send(admin_msg)

        return jsonify({"status": "success", "message": "Demande envoyée avec succès"}), 200

    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)