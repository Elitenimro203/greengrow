"""
GreenGrow — Simulateur de capteurs
===================================
Ce script simule ce que ferait l'ESP32 dans un vrai bac :
il génère de fausses données de capteurs et les envoie à l'API.

Utilité : développer et tester TOUT le backend sans avoir de hardware.
C'est la règle d'or du dev IoT : le software doit être testable sans le hardware.

Lancement : python simulator/sensor_simulator.py
"""

import time
import random
import json
import httpx  # Client HTTP — on "parle" à notre propre API

# ---- Configuration ----
API_URL = "http://localhost:8000"  # URL de notre API locale
BAC_ID = "bac_prototype_01"        # Identifiant unique du bac simulé
INTERVAL_SECONDS = 5               # Envoi toutes les 5 secondes


def generate_sensor_reading() -> dict:
    """
    Génère une lecture de capteurs réaliste pour une tomate en bonne santé.

    Pourquoi une fonction séparée ?
    Parce que dans 2 semaines, tu voudras peut-être simuler une plante malade,
    ou une panne de pompe. Tu modifieras juste cette fonction — pas le reste du code.
    C'est le principe de Single Responsibility (chaque fonction fait UNE chose).
    """
    return {
        "bac_id": BAC_ID,
        "timestamp": time.time(),
        "moisture_percent": round(random.uniform(35.0, 75.0), 1),  # % humidité sol
        "temperature_celsius": round(random.uniform(24.0, 32.0), 1),  # T° ambiante
        "humidity_air_percent": round(random.uniform(55.0, 85.0), 1),  # Humidité air
        "pump_active": False,  # La pompe est-elle en train d'arroser ?
        "source": "simulator",  # Marque les données comme simulées
    }


def send_reading(reading: dict) -> None:
    """
    Envoie une lecture à l'API et affiche le résultat.
    En cas d'erreur (API pas encore lancée, etc.), on l'affiche sans planter.
    """
    try:
        response = httpx.post(
            f"{API_URL}/api/readings",
            json=reading,
            timeout=3.0,  # On attend max 3 secondes — l'IoT ne peut pas bloquer indéfiniment
        )
        print(f"[{time.strftime('%H:%M:%S')}] ✅ Envoyé → {response.status_code} | {reading}")
    except httpx.ConnectError:
        # L'API n'est pas encore lancée — normal en début de dev
        print(f"[{time.strftime('%H:%M:%S')}] ⚠️  API non joignable — données générées quand même : {reading}")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Erreur inattendue : {e}")


def main():
    print(f"🌱 GreenGrow Simulator — Bac : {BAC_ID}")
    print(f"📡 Envoi vers : {API_URL}")
    print(f"⏱  Intervalle : {INTERVAL_SECONDS}s")
    print("─" * 50)
    print("Ctrl+C pour arrêter\n")

    while True:
        reading = generate_sensor_reading()
        send_reading(reading)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    # Pourquoi ce if __name__ == "__main__" ?
    # Ça permet d'importer ce fichier dans un test sans lancer la boucle infinie.
    # C'est une convention Python universelle — prends-la dès maintenant.
    main()
