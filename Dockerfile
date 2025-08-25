# ---------------------------
# Étape 1 : Image de base
# ---------------------------
FROM python:3.11-slim

# ---------------------------
# Étape 2 : Variables d'environnement
# ---------------------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ---------------------------
# Étape 3 : Répertoire de travail
# ---------------------------
WORKDIR /app

# ---------------------------
# Étape 4 : Copier et installer les dépendances
# ---------------------------
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------
# Étape 5 : Copier le code serveur
# ---------------------------
COPY . .

# ---------------------------
# Étape 6 : Exposer le port Modbus TCP
# ---------------------------
EXPOSE 5502

# ---------------------------
# Étape 7 : Commande par défaut pour lancer le serveur
# ---------------------------
CMD ["python", "server.py"]
