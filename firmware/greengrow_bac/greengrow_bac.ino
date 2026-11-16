// ============================================================
// GreenGrow — Firmware du bac (ESP32)
// ============================================================
// Ce programme :
//   1. lit les capteurs toutes les 2 secondes ;
//   2. décide seul d'arroser (irrigation.h), même sans réseau ;
//   3. se connecte au broker MQTT en TLS en VÉRIFIANT son certificat ;
//   4. publie ses mesures, son état et ses événements ;
//   5. reçoit ses seuils (config) et des commandes (cmd) filtrées (commands.h).
//
// Règle d'or : la pompe ne dépend jamais du réseau. Tout ce qui peut bloquer
// (connexion Wi-Fi, poignée de main TLS) n'est tenté que pompe éteinte.
// ============================================================

#include <Arduino.h>
#include <ArduinoJson.h>
#include <DHTesp.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include "commands.h"
#include "config.h"
#include "irrigation.h"
#include "secrets.h"

using namespace greengrow;

WiFiClientSecure tls;
PubSubClient mqtt(tls);
DHTesp dht;
Preferences prefs;  // petite mémoire qui survit aux coupures de courant

IrrigationController controller;
CommandGuard commandGuard;

// Dernières mesures valides
float soilMoisture = NAN;
float airTemperature = NAN;
float airHumidity = NAN;
bool reservoirOk = false;

uint32_t lastSensorMs = 0;
uint32_t lastTelemetryMs = 0;
uint32_t lastConnectAttemptMs = 0;
uint32_t connectBackoffMs = 2000;

// Événements en attente d'envoi (si le réseau est coupé au moment où ils arrivent).
struct PendingEvent {
  Event type;
  uint32_t epoch;
  float moisture;
};
const uint8_t QUEUE_SIZE = 8;
PendingEvent eventQueue[QUEUE_SIZE];
uint8_t queueCount = 0;

// ---------------- Outils ----------------

String topic(const char* channel) { return String(TOPIC_PREFIX) + "/" + channel; }

// Heure en secondes Unix, ou 0 tant que le bac ne s'est pas mis à l'heure.
uint32_t nowEpoch() {
  time_t now = time(nullptr);
  return now > 1700000000 ? (uint32_t)now : 0;
}

Inputs currentInputs() { return {millis(), soilMoisture, reservoirOk}; }

// LA seule fonction qui touche au relais : la broche suit toujours le contrôleur.
void applyPump() { digitalWrite(PIN_PUMP, controller.pumpOn() ? HIGH : LOW); }

// ---------------- Capteurs ----------------

void readSensors() {
  // Humidité du sol : moyenne de 8 lectures pour lisser le bruit.
  uint32_t sum = 0;
  for (int i = 0; i < 8; i++) sum += analogRead(PIN_SOIL);
  int raw = sum / 8;
  if (raw < SOIL_RAW_MARGIN || raw > 4095 - SOIL_RAW_MARGIN) {
    soilMoisture = NAN;  // capteur débranché ou en court-circuit
  } else {
    float percent = 100.0f * (raw - SOIL_RAW_DRY) / (float)(SOIL_RAW_WET - SOIL_RAW_DRY);
    soilMoisture = constrain(percent, 0.0f, 100.0f);
  }

  // Flotteur : entrée tirée vers le haut. LOW = de l'eau. Si le fil casse,
  // on lit HIGH = "vide" : la panne penche du côté sûr.
  reservoirOk = digitalRead(PIN_RESERVOIR) == LOW;

  // Air : en cas d'échec de lecture, on garde la dernière valeur valide.
  TempAndHumidity air = dht.getTempAndHumidity();
  if (!isnan(air.temperature) && !isnan(air.humidity)) {
    airTemperature = air.temperature;
    airHumidity = air.humidity;
  }
}

// ---------------- Événements ----------------

void queueEvent(Event type) {
  Serial.printf("[evenement] %s\n", eventName(type));
  if (queueCount == QUEUE_SIZE) {  // file pleine : on oublie le plus ancien
    memmove(eventQueue, eventQueue + 1, sizeof(PendingEvent) * (QUEUE_SIZE - 1));
    queueCount--;
  }
  eventQueue[queueCount++] = {type, nowEpoch(), soilMoisture};

  // Le mode sécurité est mémorisé : un redémarrage ne doit pas l'effacer.
  if (type == Event::FAULT_NO_MOISTURE_RISE || type == Event::FAULT_SENSOR) prefs.putBool("fault", true);
  if (type == Event::FAULT_CLEARED) prefs.putBool("fault", false);
}

void flushEvents() {
  while (queueCount > 0 && mqtt.connected()) {
    JsonDocument doc;
    doc["type"] = eventName(eventQueue[0].type);
    if (eventQueue[0].epoch) doc["timestamp"] = eventQueue[0].epoch;
    if (!isnan(eventQueue[0].moisture)) doc["moisture_percent"] = eventQueue[0].moisture;
    char payload[160];
    serializeJson(doc, payload);
    if (!mqtt.publish(topic("event").c_str(), payload)) return;  // on réessaiera
    memmove(eventQueue, eventQueue + 1, sizeof(PendingEvent) * (QUEUE_SIZE - 1));
    queueCount--;
  }
}

void publishAck(const char* id, const char* result, const char* reason) {
  JsonDocument doc;
  doc["type"] = "cmd_ack";
  doc["id"] = id;
  doc["result"] = result;  // "executed" ou "rejected"
  if (reason) doc["reason"] = reason;
  if (nowEpoch()) doc["timestamp"] = nowEpoch();
  char payload[200];
  serializeJson(doc, payload);
  mqtt.publish(topic("event").c_str(), payload);
  Serial.printf("[commande] %s -> %s %s\n", id, result, reason ? reason : "");
}

// ---------------- Messages reçus ----------------

// Nouveaux seuils envoyés par le serveur. Tout est revérifié ici : le
// firmware ne fait pas confiance au serveur pour sa sécurité physique.
void handleConfig(JsonDocument& doc) {
  IrrigationConfig c = controller.config();
  c.moistureLow = doc["moisture_low"] | c.moistureLow;
  c.moistureHigh = doc["moisture_high"] | c.moistureHigh;
  if (doc["max_watering_s"].is<uint32_t>()) c.maxWateringMs = doc["max_watering_s"].as<uint32_t>() * 1000UL;
  if (doc["min_pause_s"].is<uint32_t>()) c.minPauseMs = doc["min_pause_s"].as<uint32_t>() * 1000UL;
  if (doc["max_per_day"].is<uint8_t>()) c.maxPerDay = doc["max_per_day"].as<uint8_t>();
  c.automatic = doc["auto"] | c.automatic;

  if (controller.setConfig(c)) {
    Serial.printf("[config] seuils %.0f %% / %.0f %%\n", c.moistureLow, c.moistureHigh);
  } else {
    Serial.println("[config] REFUSEE : valeurs incoherentes ou dangereuses, on garde l'ancienne");
  }
}

void handleCommand(JsonDocument& doc) {
  const char* id = doc["id"] | "";
  const char* type = doc["type"] | "";
  uint32_t expiresAt = doc["expires_at"] | 0;

  CommandCheck check = commandGuard.check(id, expiresAt, nowEpoch());
  if (check != CommandCheck::ACCEPTED) {
    // Un identifiant invalide ne mérite même pas de réponse.
    if (check != CommandCheck::BAD_ID) publishAck(id, "rejected", commandCheckName(check));
    return;
  }

  if (strcmp(type, "pump_on") == 0) {
    uint32_t durationS = doc["duration_s"] | 10;
    StartResult r = controller.manualStart(currentInputs(), durationS * 1000UL);
    applyPump();
    switch (r) {
      case StartResult::STARTED:
        queueEvent(Event::WATERING_STARTED);
        publishAck(id, "executed", nullptr);
        break;
      case StartResult::REFUSED_FAULT: publishAck(id, "rejected", "fault"); break;
      case StartResult::REFUSED_RESERVOIR: publishAck(id, "rejected", "reservoir_empty"); break;
      case StartResult::REFUSED_DAILY_LIMIT: publishAck(id, "rejected", "daily_limit"); break;
      case StartResult::REFUSED_BUSY: publishAck(id, "rejected", "already_watering"); break;
    }
  } else if (strcmp(type, "pump_off") == 0) {
    if (controller.manualStop(currentInputs())) queueEvent(Event::STOPPED_MANUAL);
    applyPump();
    publishAck(id, "executed", nullptr);
  } else if (strcmp(type, "reset_fault") == 0) {
    if (controller.clearFault(millis())) queueEvent(Event::FAULT_CLEARED);
    publishAck(id, "executed", nullptr);
  } else {
    publishAck(id, "rejected", "unknown_type");
  }
}

void onMqttMessage(char* rawTopic, byte* payload, unsigned int length) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, length) || !doc.is<JsonObject>()) {
    Serial.println("[mqtt] message illisible ignore");
    return;
  }
  String t(rawTopic);
  if (t == topic("config")) handleConfig(doc);
  else if (t == topic("cmd")) handleCommand(doc);
}

// ---------------- Réseau ----------------

void connectMqtt() {
  // Sans l'heure, impossible de vérifier les dates de validité du certificat.
  if (WiFi.status() != WL_CONNECTED || nowEpoch() == 0) return;

  Serial.printf("[mqtt] connexion a %s:%d ...\n", MQTT_HOST, MQTT_PORT);
  // Last Will : si le bac disparaît, le broker publiera "offline" à sa place.
  bool ok = mqtt.connect(MQTT_USERNAME, MQTT_USERNAME, MQTT_PASSWORD,
                         topic("status").c_str(), 1, true, "offline");
  if (!ok) {
    // Certificat refusé, mauvais mot de passe, broker éteint... On réessaie
    // plus tard, de moins en moins souvent, et l'arrosage local continue.
    Serial.printf("[mqtt] echec (code %d), nouvel essai dans %lu s\n", mqtt.state(),
                  (unsigned long)(connectBackoffMs / 1000));
    connectBackoffMs = min(connectBackoffMs * 2, (uint32_t)60000);
    return;
  }
  connectBackoffMs = 2000;
  Serial.println("[mqtt] connecte en TLS, certificat du broker verifie");
  mqtt.publish(topic("status").c_str(), "online", true);
  mqtt.subscribe(topic("config").c_str(), 1);
  mqtt.subscribe(topic("cmd").c_str(), 1);
}

void publishTelemetry() {
  // Sans mesure fiable du sol ou de l'air, on n'envoie pas de chiffres faux.
  if (isnan(soilMoisture) || isnan(airTemperature)) return;
  JsonDocument doc;
  if (nowEpoch()) doc["timestamp"] = nowEpoch();
  doc["moisture_percent"] = round(soilMoisture * 10) / 10.0;
  doc["temperature_celsius"] = round(airTemperature * 10) / 10.0;
  doc["humidity_air_percent"] = round(airHumidity * 10) / 10.0;
  doc["pump_active"] = controller.pumpOn();
  doc["reservoir_ok"] = reservoirOk;
  doc["state"] = stateName(controller.state());
  doc["waterings_today"] = controller.countToday();
  char payload[256];
  serializeJson(doc, payload);
  mqtt.publish(topic("telemetry").c_str(), payload);
  Serial.printf("[mesure] %s\n", payload);
}

// ---------------- Démarrage ----------------

void setup() {
  // La pompe d'abord : éteinte avant toute autre chose.
  pinMode(PIN_PUMP, OUTPUT);
  digitalWrite(PIN_PUMP, LOW);
  pinMode(PIN_STATUS_LED, OUTPUT);
  pinMode(PIN_RESERVOIR, INPUT_PULLUP);

  Serial.begin(115200);
  Serial.println("\n=== GreenGrow - bac " MQTT_USERNAME " ===");

  dht.setup(PIN_DHT, DHTesp::DHT22);
  analogReadResolution(12);

  IrrigationConfig cfg;
  cfg.maxWateringMs = DEFAULT_MAX_WATERING_MS;
  cfg.minPauseMs = DEFAULT_MIN_PAUSE_MS;
  cfg.soakMs = DEFAULT_SOAK_MS;
  controller.setConfig(cfg);

  prefs.begin("greengrow", false);
  if (prefs.getBool("fault", false)) {
    controller.restoreFault();
    Serial.println("[securite] mode securite memorise avant le redemarrage : pompe bloquee");
  }

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.google.com");  // heure UTC par NTP

  // LA ligne de sécurité : on ne fait confiance qu'aux certificats signés par
  // notre autorité. Ne JAMAIS la remplacer par tls.setInsecure(), qui
  // accepterait n'importe quel serveur, y compris un imposteur.
  tls.setCACert(CA_CERT);
  tls.setHandshakeTimeout(10);

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
  mqtt.setBufferSize(768);
  mqtt.setKeepAlive(60);
}

// ---------------- Boucle principale ----------------

void loop() {
  uint32_t now = millis();

  // 1. Capteurs et décision d'arrosage : toujours, réseau ou pas.
  if (now - lastSensorMs >= SENSOR_INTERVAL_MS) {
    lastSensorMs = now;
    readSensors();
    Event event = controller.update(currentInputs());
    applyPump();
    if (event != Event::NONE) queueEvent(event);
  }

  // 2. Réseau. Une tentative de connexion peut bloquer plusieurs secondes :
  //    on ne la fait JAMAIS pendant que la pompe tourne.
  if (mqtt.connected()) {
    mqtt.loop();
    flushEvents();
    if (now - lastTelemetryMs >= TELEMETRY_INTERVAL_MS) {
      lastTelemetryMs = now;
      publishTelemetry();
    }
  } else if (!controller.pumpOn() && now - lastConnectAttemptMs >= connectBackoffMs) {
    lastConnectAttemptMs = now;
    connectMqtt();
  }

  // 3. LED : fixe = connecté, clignotement rapide = mode sécurité, éteinte = hors ligne.
  if (controller.state() == State::FAULT) digitalWrite(PIN_STATUS_LED, (now / 200) % 2);
  else digitalWrite(PIN_STATUS_LED, mqtt.connected() ? HIGH : LOW);
}
