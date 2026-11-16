// ============================================================
// GreenGrow — Logique d'arrosage
// ============================================================
// Ce fichier décide QUAND la pompe tourne. Il ne touche à aucun matériel :
// on lui donne l'heure et les mesures, il répond "pompe allumée ou non".
// Grâce à ça, il est testé automatiquement sur un PC (firmware/tests/),
// sans ESP32 : chaque garde-fou a son test.
//
// Machine à états :
//
//   IDLE ──(sol sec, réservoir ok, pause écoulée, quota ok)──> WATERING
//   WATERING ──(sol assez humide / durée max / réservoir vide)──> SOAKING
//   SOAKING ──(l'eau a eu le temps de pénétrer : l'humidité a-t-elle monté ?)
//        ├── oui ──> IDLE
//        └── non ──> FAULT   (tuyau débranché, pompe en panne, capteur faux)
//   tout état ──(capteur du sol incohérent)──> FAULT
//   FAULT ──(intervention humaine : commande reset)──> IDLE
//
// En FAULT (mode sécurité), la pompe ne démarre plus : mieux vaut une plante
// qui a soif quelques heures qu'un bac noyé ou une pompe qui tourne à vide.
// ============================================================
#pragma once

#include <math.h>
#include <stdint.h>

namespace greengrow {

// Limites absolues, compilées dans le firmware. Aucune configuration reçue
// par le réseau ne peut les dépasser : même un serveur piraté ne peut pas
// demander 2 heures d'arrosage.
const uint32_t HARD_MAX_WATERING_MS = 120UL * 1000UL;
const uint8_t HARD_MAX_PER_DAY = 12;
const uint32_t DAY_MS = 24UL * 3600UL * 1000UL;

struct IrrigationConfig {
  float moistureLow = 45.0f;            // on arrose en dessous (%)
  float moistureHigh = 80.0f;           // on arrête au-dessus (%)
  uint32_t maxWateringMs = 30000;       // durée max d'UN arrosage
  uint32_t minPauseMs = 10UL * 60000UL; // pause obligatoire entre deux arrosages
  uint8_t maxPerDay = 6;                // arrosages max par 24 h
  uint32_t soakMs = 120000;             // temps laissé à l'eau pour pénétrer
  float minRise = 2.0f;                 // hausse d'humidité attendue après arrosage (points de %)
  bool automatic = true;                // false = seules les commandes manuelles arrosent
};

// Vérifie une configuration reçue. Une configuration incohérente est refusée
// en bloc : on garde l'ancienne.
inline bool isValidConfig(const IrrigationConfig& c) {
  return c.moistureLow >= 5.0f && c.moistureHigh <= 95.0f &&
         c.moistureLow + 5.0f <= c.moistureHigh &&
         c.maxWateringMs >= 1000 && c.maxWateringMs <= HARD_MAX_WATERING_MS &&
         c.minPauseMs >= 60000 && c.maxPerDay >= 1 && c.maxPerDay <= HARD_MAX_PER_DAY &&
         c.soakMs >= 10000 && c.soakMs <= c.minPauseMs && c.minRise >= 0.5f;
}

enum class State : uint8_t { IDLE, WATERING, SOAKING, FAULT };

enum class Event : uint8_t {
  NONE,
  WATERING_STARTED,
  STOPPED_TARGET_REACHED,   // le sol est assez humide : arrêt normal
  STOPPED_MAX_DURATION,     // durée max atteinte
  STOPPED_RESERVOIR_EMPTY,
  STOPPED_MANUAL,
  FAULT_NO_MOISTURE_RISE,   // on a arrosé mais le sol n'est pas plus humide
  FAULT_SENSOR,             // le capteur du sol renvoie n'importe quoi
  FAULT_CLEARED,
  DAILY_LIMIT_REACHED,
  RESERVOIR_EMPTY,
  RESERVOIR_OK,
};

enum class StartResult : uint8_t { STARTED, REFUSED_FAULT, REFUSED_RESERVOIR, REFUSED_DAILY_LIMIT, REFUSED_BUSY };

struct Inputs {
  uint32_t nowMs;       // millis() : temps écoulé depuis le démarrage
  float moisture;       // humidité du sol en %, ou NAN si le capteur est invalide
  bool reservoirOk;     // false = réservoir vide
};

class IrrigationController {
 public:
  explicit IrrigationController(const IrrigationConfig& config = IrrigationConfig()) : cfg_(config) {}

  // À appeler régulièrement (toutes les 1 à 2 s). Retourne au plus un
  // événement par appel, à publier vers le serveur.
  Event update(const Inputs& in) {
    rollDailyWindow(in.nowMs);

    // 1. Capteur du sol : trois lectures invalides de suite = panne.
    //    (une seule peut être un parasite, on ne s'affole pas pour ça)
    if (isnan(in.moisture)) {
      if (invalidCount_ < 255) invalidCount_++;
      if (invalidCount_ >= 3 && state_ != State::FAULT) return enterFault(Event::FAULT_SENSOR);
      // Sans mesure fiable on ne décide rien, mais on continue de surveiller
      // la durée max et le réservoir si la pompe tourne déjà.
    } else {
      invalidCount_ = 0;
    }

    // 2. Réservoir : signalé une fois quand il se vide, une fois quand il est rempli.
    if (in.reservoirOk != reservoirOk_) {
      reservoirOk_ = in.reservoirOk;
      if (!reservoirOk_ && state_ == State::WATERING) return stop(in, Event::STOPPED_RESERVOIR_EMPTY, false);
      return reservoirOk_ ? Event::RESERVOIR_OK : Event::RESERVOIR_EMPTY;
    }

    switch (state_) {
      case State::IDLE:
        if (!cfg_.automatic || isnan(in.moisture) || in.moisture >= cfg_.moistureLow) break;
        if (!reservoirOk_) break;
        if (everWatered_ && in.nowMs - lastStopMs_ < cfg_.minPauseMs) break;  // pause obligatoire
        if (countToday_ >= cfg_.maxPerDay) {
          if (!limitReported_) { limitReported_ = true; return Event::DAILY_LIMIT_REACHED; }
          break;
        }
        return start(in, cfg_.maxWateringMs, false);

      case State::WATERING:
        if (!reservoirOk_) return stop(in, Event::STOPPED_RESERVOIR_EMPTY, false);
        if (in.nowMs - startMs_ >= limitMs_)
          return stop(in, manual_ ? Event::STOPPED_MANUAL : Event::STOPPED_MAX_DURATION, true);
        if (!manual_ && !isnan(in.moisture) && in.moisture >= cfg_.moistureHigh)
          return stop(in, Event::STOPPED_TARGET_REACHED, false);
        break;

      case State::SOAKING:
        if (in.nowMs - lastStopMs_ < cfg_.soakMs) break;
        state_ = State::IDLE;
        // L'eau a eu le temps de pénétrer. Si on a arrosé et que le sol n'est
        // pas plus humide, quelque chose ne va pas : on arrête tout.
        if (verifyRise_ && !isnan(in.moisture) && in.moisture < startMoisture_ + cfg_.minRise)
          return enterFault(Event::FAULT_NO_MOISTURE_RISE);
        break;

      case State::FAULT:
        break;  // on n'en sort que par clearFault()
    }
    return Event::NONE;
  }

  // Commande manuelle "arrose N secondes". Elle passe outre le seuil et la
  // pause, mais JAMAIS le mode sécurité, le réservoir vide, le quota du jour
  // ni la durée max.
  StartResult manualStart(const Inputs& in, uint32_t durationMs) {
    rollDailyWindow(in.nowMs);
    if (state_ == State::FAULT) return StartResult::REFUSED_FAULT;
    if (state_ == State::WATERING) return StartResult::REFUSED_BUSY;
    if (!in.reservoirOk) return StartResult::REFUSED_RESERVOIR;
    if (countToday_ >= cfg_.maxPerDay) return StartResult::REFUSED_DAILY_LIMIT;
    start(in, durationMs < cfg_.maxWateringMs ? durationMs : cfg_.maxWateringMs, true);
    return StartResult::STARTED;
  }

  // Commande manuelle "arrête". Toujours acceptée.
  bool manualStop(const Inputs& in) {
    if (state_ != State::WATERING) return false;
    stop(in, Event::STOPPED_MANUAL, true);
    return true;
  }

  // Sortie du mode sécurité, après vérification humaine du bac.
  bool clearFault(uint32_t nowMs) {
    if (state_ != State::FAULT) return false;
    state_ = State::IDLE;
    invalidCount_ = 0;
    lastStopMs_ = nowMs;  // on repart avec une pause complète
    everWatered_ = true;
    return true;
  }

  // Au démarrage : reprendre le mode sécurité mémorisé avant la coupure.
  // Sans ça, il suffirait de redémarrer le bac pour contourner la sécurité.
  void restoreFault() { state_ = State::FAULT; }

  bool setConfig(const IrrigationConfig& c) {
    if (!isValidConfig(c)) return false;
    cfg_ = c;
    return true;
  }

  bool pumpOn() const { return state_ == State::WATERING; }
  State state() const { return state_; }
  uint8_t countToday() const { return countToday_; }
  const IrrigationConfig& config() const { return cfg_; }

 private:
  Event start(const Inputs& in, uint32_t limitMs, bool manual) {
    state_ = State::WATERING;
    startMs_ = in.nowMs;
    limitMs_ = limitMs;
    manual_ = manual;
    startMoisture_ = in.moisture;
    countToday_++;
    return Event::WATERING_STARTED;
  }

  Event stop(const Inputs& in, Event reason, bool verifyRise) {
    state_ = State::SOAKING;
    lastStopMs_ = in.nowMs;
    everWatered_ = true;
    // On ne vérifie la hausse que si la pompe a tourné assez longtemps pour
    // que de l'eau soit vraiment arrivée, et si on connaissait l'humidité de départ.
    verifyRise_ = verifyRise && !isnan(startMoisture_) && in.nowMs - startMs_ >= 5000;
    return reason;
  }

  Event enterFault(Event reason) {
    state_ = State::FAULT;
    return reason;
  }

  // Le quota "par jour" est une fenêtre glissante de 24 h comptée avec
  // millis() : elle fonctionne même si le bac ne connaît pas l'heure.
  void rollDailyWindow(uint32_t nowMs) {
    if (nowMs - windowStartMs_ >= DAY_MS) {
      windowStartMs_ = nowMs;
      countToday_ = 0;
      limitReported_ = false;
    }
  }

  IrrigationConfig cfg_;
  State state_ = State::IDLE;
  bool reservoirOk_ = true;
  bool manual_ = false;
  bool verifyRise_ = false;
  bool everWatered_ = false;
  bool limitReported_ = false;
  uint8_t invalidCount_ = 0;
  uint8_t countToday_ = 0;
  uint32_t startMs_ = 0;
  uint32_t limitMs_ = 0;
  uint32_t lastStopMs_ = 0;
  uint32_t windowStartMs_ = 0;
  float startMoisture_ = NAN;
};

inline const char* eventName(Event e) {
  switch (e) {
    case Event::WATERING_STARTED: return "watering_started";
    case Event::STOPPED_TARGET_REACHED: return "watering_stopped_target";
    case Event::STOPPED_MAX_DURATION: return "watering_stopped_max_duration";
    case Event::STOPPED_RESERVOIR_EMPTY: return "watering_stopped_reservoir_empty";
    case Event::STOPPED_MANUAL: return "watering_stopped_manual";
    case Event::FAULT_NO_MOISTURE_RISE: return "fault_no_moisture_rise";
    case Event::FAULT_SENSOR: return "fault_sensor";
    case Event::FAULT_CLEARED: return "fault_cleared";
    case Event::DAILY_LIMIT_REACHED: return "daily_limit_reached";
    case Event::RESERVOIR_EMPTY: return "reservoir_empty";
    case Event::RESERVOIR_OK: return "reservoir_ok";
    default: return "none";
  }
}

inline const char* stateName(State s) {
  switch (s) {
    case State::WATERING: return "watering";
    case State::SOAKING: return "soaking";
    case State::FAULT: return "fault";
    default: return "idle";
  }
}

}  // namespace greengrow
