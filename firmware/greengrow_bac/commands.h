// ============================================================
// GreenGrow — Filtre des commandes reçues
// ============================================================
// Une commande de pompe est dangereuse si elle arrive au mauvais moment.
// Exemple : tu cliques "arroser" alors que le bac est hors ligne ; le broker
// garde le message ; le bac se reconnecte 3 heures plus tard et arrose en
// pleine nuit. Ou bien le réseau livre deux fois le même message (QoS 1 =
// "au moins une fois") et le bac arrose deux fois.
//
// Chaque commande porte donc :
//   - un identifiant unique  -> une commande n'est exécutée qu'UNE fois
//   - une heure limite       -> passé ce délai, elle est ignorée
// ============================================================
#pragma once

#include <stdint.h>
#include <string.h>

namespace greengrow {

const uint32_t MAX_COMMAND_LIFETIME_S = 300;  // une commande valable plus de 5 min est suspecte
const uint8_t REMEMBERED_IDS = 16;
const uint8_t MAX_ID_LEN = 36;                // la taille d'un UUID

enum class CommandCheck : uint8_t { ACCEPTED, NO_CLOCK, EXPIRED, TOO_FAR_IN_FUTURE, DUPLICATE, BAD_ID };

class CommandGuard {
 public:
  // nowEpoch : heure actuelle en secondes Unix (0 si le bac n'a pas l'heure).
  CommandCheck check(const char* id, uint32_t expiresAtEpoch, uint32_t nowEpoch) {
    if (id == nullptr || id[0] == '\0' || strlen(id) > MAX_ID_LEN) return CommandCheck::BAD_ID;
    // Sans horloge, impossible de savoir si la commande est périmée :
    // dans le doute, on refuse.
    if (nowEpoch < 1700000000UL) return CommandCheck::NO_CLOCK;
    if (expiresAtEpoch <= nowEpoch) return CommandCheck::EXPIRED;
    if (expiresAtEpoch - nowEpoch > MAX_COMMAND_LIFETIME_S) return CommandCheck::TOO_FAR_IN_FUTURE;
    for (uint8_t i = 0; i < REMEMBERED_IDS; i++)
      if (strcmp(seen_[i], id) == 0) return CommandCheck::DUPLICATE;

    // Acceptée : on retient son identifiant (les plus anciens sont oubliés,
    // ce qui est sans risque puisqu'ils sont expirés depuis longtemps).
    strncpy(seen_[next_], id, MAX_ID_LEN);
    seen_[next_][MAX_ID_LEN] = '\0';
    next_ = (next_ + 1) % REMEMBERED_IDS;
    return CommandCheck::ACCEPTED;
  }

 private:
  char seen_[REMEMBERED_IDS][MAX_ID_LEN + 1] = {};
  uint8_t next_ = 0;
};

inline const char* commandCheckName(CommandCheck c) {
  switch (c) {
    case CommandCheck::ACCEPTED: return "accepted";
    case CommandCheck::NO_CLOCK: return "no_clock";
    case CommandCheck::EXPIRED: return "expired";
    case CommandCheck::TOO_FAR_IN_FUTURE: return "expiry_too_far";
    case CommandCheck::DUPLICATE: return "duplicate";
    default: return "bad_id";
  }
}

}  // namespace greengrow
