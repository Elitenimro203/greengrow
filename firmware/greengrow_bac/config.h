// ============================================================
// GreenGrow — Réglages du firmware (rien de secret ici)
// ============================================================
#pragma once

// ---- Broches ----
#define PIN_DHT 15          // capteur température / humidité de l'air (DHT22)
#define PIN_SOIL 34         // capteur d'humidité du sol (entrée analogique)
#define PIN_RESERVOIR 27    // flotteur du réservoir : relié à la masse = il y a de l'eau
#define PIN_PUMP 26         // relais de la pompe (et LED "pompe" sur Wokwi)
#define PIN_STATUS_LED 2    // LED de la carte : allumée = connecté au serveur

// ---- Capteur d'humidité du sol ----
// Valeurs brutes (0 à 4095) lues quand le sol est totalement sec / détrempé.
// Sur Wokwi le capteur est un potentiomètre : 0 = sec, 4095 = détrempé.
// Avec un vrai capteur capacitif, ces deux valeurs se mesurent (étape 5).
#define SOIL_RAW_DRY 0
#define SOIL_RAW_WET 4095
// Un capteur débranché ou en court-circuit colle à une extrémité :
// à moins de SOIL_RAW_MARGIN d'un bord, la lecture est jugée invalide.
#define SOIL_RAW_MARGIN 40

// ---- Rythme ----
#define SENSOR_INTERVAL_MS 2000

// DEMO_MODE = 1 : tout va plus vite, pour voir le comportement sur Wokwi sans
// attendre 10 minutes. Mettre 0 pour le vrai bac.
#define DEMO_MODE 1

#if DEMO_MODE
#define TELEMETRY_INTERVAL_MS 10000
#define DEFAULT_MAX_WATERING_MS 10000   // 10 s d'arrosage max
#define DEFAULT_MIN_PAUSE_MS 60000      // 1 min de pause
#define DEFAULT_SOAK_MS 20000           // vérification 20 s après l'arrosage
#else
#define TELEMETRY_INTERVAL_MS 60000
#define DEFAULT_MAX_WATERING_MS 30000
#define DEFAULT_MIN_PAUSE_MS 600000
#define DEFAULT_SOAK_MS 120000
#endif
