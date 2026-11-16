// Tests de la logique du firmware, exécutés sur un PC (pas besoin d'ESP32) :
//   g++ -std=c++17 -Wall -Wextra -o test_logic test_logic.cpp && ./test_logic
//
// Chaque test raconte un scénario et vérifie ce que fait la pompe.

#include <cstdio>
#include <cstdlib>

#include "../greengrow_bac/commands.h"
#include "../greengrow_bac/irrigation.h"

using namespace greengrow;

static int failures = 0;
static const char* current = "";

#define CHECK(cond)                                                              \
  do {                                                                           \
    if (!(cond)) {                                                               \
      printf("  ECHEC  %s  (ligne %d) : %s\n", current, __LINE__, #cond);        \
      failures++;                                                                \
    }                                                                            \
  } while (0)

#define TEST(name)            \
  static void name();         \
  struct name##_reg {         \
    name##_reg() {            \
      current = #name;        \
      name();                 \
      printf("  ok     %s\n", #name); \
    }                         \
  } name##_instance;          \
  static void name()

const uint32_t S = 1000, MIN = 60 * S;

// Un petit banc d'essai : un contrôleur, une horloge, un sol.
struct Bench {
  IrrigationController ctl;
  uint32_t now = 0;
  float moisture = 60;
  bool reservoir = true;

  Event tick(uint32_t advanceMs = 2 * S) {
    now += advanceMs;
    return ctl.update({now, moisture, reservoir});
  }
  // Avance le temps par pas de 2 s et retourne le premier événement rencontré.
  Event run(uint32_t durationMs) {
    for (uint32_t t = 0; t < durationMs; t += 2 * S) {
      Event e = tick();
      if (e != Event::NONE) return e;
    }
    return Event::NONE;
  }
  Inputs in() { return {now, moisture, reservoir}; }
};

TEST(sol_humide_la_pompe_reste_eteinte) {
  Bench b;
  CHECK(b.run(10 * MIN) == Event::NONE);
  CHECK(!b.ctl.pumpOn());
}

TEST(sol_sec_la_pompe_demarre_puis_s_arrete_au_seuil_haut) {
  Bench b;
  b.moisture = 40;
  CHECK(b.tick() == Event::WATERING_STARTED);
  CHECK(b.ctl.pumpOn());
  b.moisture = 81;
  CHECK(b.tick() == Event::STOPPED_TARGET_REACHED);
  CHECK(!b.ctl.pumpOn());
}

TEST(la_pompe_ne_tourne_jamais_plus_que_la_duree_max) {
  Bench b;
  b.moisture = 40;
  b.tick();
  b.moisture = 50;  // ça monte, mais pas jusqu'au seuil haut
  CHECK(b.run(60 * S) == Event::STOPPED_MAX_DURATION);
  CHECK(!b.ctl.pumpOn());
  CHECK(b.now <= 2 * S + 30 * S + 2 * S);  // 30 s max, à un pas de mesure près
}

TEST(pause_obligatoire_entre_deux_arrosages) {
  Bench b;
  b.moisture = 40;
  b.tick();
  b.moisture = 50;
  b.run(60 * S);    // arrêt à la durée max
  b.moisture = 44;  // l'humidité a monté (+4) mais le sol est encore sec
  CHECK(b.run(9 * MIN) == Event::NONE);  // toujours en pause : pas d'arrosage
  CHECK(!b.ctl.pumpOn());
  CHECK(b.run(2 * MIN) == Event::WATERING_STARTED);  // pause écoulée
}

TEST(pas_plus_de_six_arrosages_par_jour) {
  Bench b;
  int started = 0;
  bool limitSignaled = false;
  b.moisture = 40;
  for (uint32_t t = 0; t < 20UL * 60 * MIN; t += 2 * S) {  // 20 heures de sol sec
    Event e = b.tick();
    if (e == Event::WATERING_STARTED) { started++; b.moisture = 40; }
    if (b.ctl.pumpOn()) b.moisture += 0.5f;            // l'eau arrive
    else if (b.moisture > 40) b.moisture -= 0.05f;     // puis le sol sèche vite
    if (e == Event::DAILY_LIMIT_REACHED) limitSignaled = true;
  }
  CHECK(started == 6);
  CHECK(limitSignaled);
  CHECK(b.ctl.state() != State::FAULT);
}

TEST(le_quota_repart_apres_24_heures) {
  Bench b;
  b.moisture = 40;
  for (int i = 0; i < 6; i++) {
    CHECK(b.ctl.manualStart(b.in(), 2 * S) == StartResult::STARTED);
    b.ctl.manualStop(b.in());
  }
  CHECK(b.ctl.manualStart(b.in(), 2 * S) == StartResult::REFUSED_DAILY_LIMIT);
  b.now += DAY_MS;
  CHECK(b.ctl.manualStart(b.in(), 2 * S) == StartResult::STARTED);
}

TEST(reservoir_vide_la_pompe_ne_demarre_pas) {
  Bench b;
  b.reservoir = false;
  b.moisture = 30;
  CHECK(b.tick() == Event::RESERVOIR_EMPTY);  // signalé une fois
  CHECK(b.run(30 * MIN) == Event::NONE);
  CHECK(!b.ctl.pumpOn());
  b.reservoir = true;
  CHECK(b.tick() == Event::RESERVOIR_OK);
  CHECK(b.tick() == Event::WATERING_STARTED);  // rempli : on arrose
}

TEST(reservoir_qui_se_vide_pendant_l_arrosage_coupe_la_pompe) {
  Bench b;
  b.moisture = 40;
  b.tick();
  b.reservoir = false;
  CHECK(b.tick() == Event::STOPPED_RESERVOIR_EMPTY);
  CHECK(!b.ctl.pumpOn());
  CHECK(b.run(5 * MIN) == Event::NONE);  // pas de fausse panne "humidité qui ne monte pas"
  CHECK(b.ctl.state() != State::FAULT);
}

TEST(arroser_sans_que_l_humidite_monte_declenche_le_mode_securite) {
  Bench b;
  b.moisture = 40;  // tuyau débranché : la pompe tourne, le sol reste sec
  b.tick();
  CHECK(b.run(60 * S) == Event::STOPPED_MAX_DURATION);
  CHECK(b.run(5 * MIN) == Event::FAULT_NO_MOISTURE_RISE);
  CHECK(b.ctl.state() == State::FAULT);
  CHECK(b.run(24 * 60 * MIN) == Event::NONE);  // plus AUCUN arrosage, même un jour après
  CHECK(!b.ctl.pumpOn());
}

TEST(capteur_du_sol_en_panne_declenche_le_mode_securite) {
  Bench b;
  b.moisture = NAN;
  CHECK(b.tick() == Event::NONE);  // une lecture ratée : on patiente
  CHECK(b.tick() == Event::NONE);
  CHECK(b.tick() == Event::FAULT_SENSOR);  // trois de suite : panne
  b.moisture = 20;                         // même si une valeur "sèche" revient
  CHECK(b.run(30 * MIN) == Event::NONE);
  CHECK(!b.ctl.pumpOn());
}

TEST(une_lecture_ratee_isolee_ne_declenche_rien) {
  Bench b;
  b.moisture = NAN;
  b.tick();
  b.moisture = 60;
  CHECK(b.run(10 * MIN) == Event::NONE);
  CHECK(b.ctl.state() == State::IDLE);
}

TEST(capteur_qui_tombe_en_panne_pendant_l_arrosage_coupe_la_pompe) {
  Bench b;
  b.moisture = 40;
  b.tick();
  b.moisture = NAN;
  b.tick(); b.tick();
  CHECK(b.tick() == Event::FAULT_SENSOR);
  CHECK(!b.ctl.pumpOn());
}

TEST(le_mode_securite_ne_se_leve_que_sur_intervention) {
  Bench b;
  b.moisture = NAN;
  b.tick(); b.tick(); b.tick();
  b.moisture = 40;
  CHECK(b.ctl.manualStart(b.in(), 10 * S) == StartResult::REFUSED_FAULT);  // même à la main
  CHECK(b.ctl.clearFault(b.now));
  CHECK(b.ctl.state() == State::IDLE);
  CHECK(b.run(9 * MIN) == Event::NONE);  // et on repart par une pause complète
  CHECK(b.run(2 * MIN) == Event::WATERING_STARTED);
}

TEST(le_mode_securite_survit_a_un_redemarrage) {
  IrrigationController ctl;
  ctl.restoreFault();  // ce que fait le firmware au démarrage s'il avait mémorisé une panne
  CHECK(ctl.update({2 * S, 20, true}) == Event::NONE);
  CHECK(!ctl.pumpOn());
}

TEST(commande_manuelle_bornee_par_la_duree_max) {
  Bench b;
  CHECK(b.ctl.manualStart(b.in(), 3600 * S) == StartResult::STARTED);  // "arrose une heure"
  CHECK(b.run(60 * S) == Event::STOPPED_MANUAL);
  CHECK(b.now <= 34 * S);  // coupé à 30 s
}

TEST(commande_manuelle_refusee_si_reservoir_vide) {
  Bench b;
  b.reservoir = false;
  CHECK(b.ctl.manualStart(b.in(), 10 * S) == StartResult::REFUSED_RESERVOIR);
  CHECK(!b.ctl.pumpOn());
}

TEST(arret_manuel_toujours_possible) {
  Bench b;
  b.moisture = 40;
  b.tick();
  CHECK(b.ctl.manualStop(b.in()));
  CHECK(!b.ctl.pumpOn());
}

TEST(mode_manuel_seul_pas_d_arrosage_automatique) {
  Bench b;
  IrrigationConfig c;
  c.automatic = false;
  CHECK(b.ctl.setConfig(c));
  b.moisture = 20;
  CHECK(b.run(30 * MIN) == Event::NONE);
}

TEST(une_configuration_dangereuse_est_refusee) {
  IrrigationController ctl;
  IrrigationConfig c;
  c.maxWateringMs = 2UL * 3600 * 1000;  // deux heures de pompe
  CHECK(!ctl.setConfig(c));
  c = IrrigationConfig(); c.moistureLow = 90; c.moistureHigh = 50;  // seuils inversés
  CHECK(!ctl.setConfig(c));
  c = IrrigationConfig(); c.maxPerDay = 200;
  CHECK(!ctl.setConfig(c));
  c = IrrigationConfig(); c.minPauseMs = 0;  // plus de pause
  CHECK(!ctl.setConfig(c));
  CHECK(ctl.config().maxWateringMs == 30000);  // l'ancienne configuration est gardée
}

TEST(le_compteur_millis_peut_deborder_sans_bloquer) {
  // millis() repasse à zéro après ~49 jours. Les durées doivent rester justes.
  Bench b;
  b.now = 0xFFFFFFFFu - 10 * S;
  b.ctl.update(b.in());
  b.moisture = 40;
  CHECK(b.tick() == Event::WATERING_STARTED);
  b.moisture = 50;
  CHECK(b.run(60 * S) == Event::STOPPED_MAX_DURATION);  // l'arrêt a lieu malgré le débordement
}

// ---------------- Commandes ----------------

const uint32_t NOW = 1800000000;

TEST(commande_valide_acceptee_une_seule_fois) {
  CommandGuard g;
  CHECK(g.check("cmd-1", NOW + 30, NOW) == CommandCheck::ACCEPTED);
  CHECK(g.check("cmd-1", NOW + 30, NOW) == CommandCheck::DUPLICATE);  // le réseau l'a livrée deux fois
  CHECK(g.check("cmd-2", NOW + 30, NOW) == CommandCheck::ACCEPTED);
}

TEST(commande_perimee_refusee) {
  CommandGuard g;
  CHECK(g.check("vieille", NOW - 1, NOW) == CommandCheck::EXPIRED);  // reçue après une reconnexion
  CHECK(g.check("pile", NOW, NOW) == CommandCheck::EXPIRED);
}

TEST(commande_valable_trop_longtemps_refusee) {
  CommandGuard g;
  CHECK(g.check("eternelle", NOW + 86400, NOW) == CommandCheck::TOO_FAR_IN_FUTURE);
}

TEST(sans_horloge_aucune_commande_n_est_executee) {
  CommandGuard g;
  CHECK(g.check("cmd", NOW + 30, 0) == CommandCheck::NO_CLOCK);
  CHECK(g.check("cmd", 60, 12) == CommandCheck::NO_CLOCK);  // horloge à "12 secondes après 1970"
}

TEST(identifiant_absent_ou_enorme_refuse) {
  CommandGuard g;
  CHECK(g.check("", NOW + 30, NOW) == CommandCheck::BAD_ID);
  CHECK(g.check(nullptr, NOW + 30, NOW) == CommandCheck::BAD_ID);
  char huge[200];
  memset(huge, 'a', sizeof(huge) - 1);
  huge[sizeof(huge) - 1] = '\0';
  CHECK(g.check(huge, NOW + 30, NOW) == CommandCheck::BAD_ID);
}

TEST(une_commande_refusee_ne_bloque_pas_son_identifiant) {
  CommandGuard g;
  CHECK(g.check("cmd", NOW - 5, NOW) == CommandCheck::EXPIRED);
  CHECK(g.check("cmd", NOW + 30, NOW) == CommandCheck::ACCEPTED);
}

int main() {
  if (failures) {
    printf("\n%d verification(s) en echec\n", failures);
    return 1;
  }
  printf("\nTous les tests du firmware passent\n");
  return 0;
}
