# Utiliser une image Python légère
FROM python:3.11-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances
COPY requirements.txt .

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Copier tout le reste du code
COPY . .

# Exposer le port que Flask utilise
EXPOSE 5000

# Lancer l'application avec Gunicorn (plus robuste que flask run)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]