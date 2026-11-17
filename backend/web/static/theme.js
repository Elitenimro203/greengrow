// Applique le thème choisi (clair / sombre) avant le premier affichage, pour
// éviter un flash de la mauvaise couleur. Sans choix enregistré, c'est le
// réglage du système qui décide (voir style.css).
(function () {
  try {
    var saved = localStorage.getItem("greengrow-theme");
    if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  } catch (e) {
    /* stockage indisponible (navigation privée) : on garde le thème du système */
  }
})();
