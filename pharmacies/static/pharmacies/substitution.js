/* Rupture de stock : demande à l'IA des remplaçants sans recharger la page (appel asynchrone).

   Accessibilité : l'état (« Recherche… », résultat) est annoncé par une zone aria-live, l'erreur par role="alert",
   le bouton est marqué aria-busy pendant l'appel. Sécurité : tout le texte reçu est inséré avec textContent
   (jamais innerHTML) et la requête porte le jeton CSRF du formulaire. */
(function () {
  "use strict";

  var DELAI_MAX_MS = 15000;
  var formulaire = document.querySelector("form[data-substitution]");
  if (!formulaire) return;

  var bouton = formulaire.querySelector("[data-suggerer]");
  var choix = formulaire.querySelector("select[name='medicament']");
  var etat = formulaire.querySelector("[data-etat]");
  var erreur = formulaire.querySelector("[data-erreur]");
  var liste = formulaire.querySelector("[data-liste]");
  var remplacant = formulaire.querySelector("input[name='remplacant']");
  var jeton = formulaire.querySelector("input[name='csrfmiddlewaretoken']").value;

  function vider() {
    erreur.textContent = "";
    while (liste.firstChild) liste.removeChild(liste.firstChild);
  }

  function element(balise, classe, texte) {
    var e = document.createElement(balise);
    if (classe) e.className = classe;
    if (texte) e.textContent = texte;
    return e;
  }

  function disponibilite(s) {
    // quantité dans CE stock : null = pas référencé ici
    if (s.stock === null || s.stock === undefined) return element("span", "sev stk-inconnu ml-2", "Pas dans votre stock");
    if (s.stock === 0) return element("span", "sev stk-rupture ml-2", "En rupture ici aussi");
    return element("span", "sev stk-ok ml-2", "En stock : " + s.stock);
  }

  function afficher(donnees) {
    // d'abord ce que la pharmacie a réellement en rayon, puis les suggestions de l'IA (ou de la table locale)
    donnees.en_stock.concat(donnees.suggestions).forEach(function (s) {
      var ligne = element("li", "proposal");
      var texte = element("span", "text-sm");
      texte.appendChild(element("strong", "font-medium", s.nom));
      texte.appendChild(element("span", "muted", " · " + s.type_libelle + (s.raison ? " · " + s.raison : "")));
      texte.appendChild(disponibilite(s));
      if (s.alerte_allergie) {
        // l'alerte est écrite en toutes lettres : la couleur seule ne suffit pas
        texte.appendChild(element("span", "sev sev-severe ml-2", "Allergie du patient : " + s.alerte_allergie));
      }
      var utiliser = element("button", "abtn abtn-outline", "Utiliser");
      utiliser.type = "button";
      utiliser.appendChild(element("span", "sr-only", " " + s.nom));
      utiliser.addEventListener("click", function () {
        remplacant.value = s.nom;
        remplacant.focus();
      });
      ligne.appendChild(texte);
      ligne.appendChild(utiliser);
      liste.appendChild(ligne);
    });
    var bilan = donnees.en_stock.length + " équivalent(s) dans votre stock et " + donnees.suggestions.length +
      " suggestion(s) pour " + donnees.medicament + ". " + donnees.message;
    if (donnees.source === "ia") bilan += " (" + (donnees.en_cache ? "réponse déjà connue" : donnees.duree_ms + " ms") + ")";
    etat.textContent = bilan;
  }

  bouton.addEventListener("click", function () {
    vider();
    if (!choix.value) {
      erreur.textContent = "Choisissez d'abord le médicament en rupture.";
      choix.focus();
      return;
    }
    var corps = new FormData();
    corps.append("medicament", choix.value);
    var annulation = new AbortController();
    var minuteur = setTimeout(function () { annulation.abort(); }, DELAI_MAX_MS);

    bouton.disabled = true;
    bouton.setAttribute("aria-busy", "true");
    etat.textContent = "Recherche de remplaçants en cours…";

    fetch(formulaire.dataset.substitution, {
      method: "POST",
      body: corps,
      headers: { "X-CSRFToken": jeton, "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      signal: annulation.signal,
    })
      .then(function (reponse) {
        return reponse.json().catch(function () { return {}; }).then(function (donnees) {
          if (!reponse.ok || !donnees.ok) throw new Error(donnees.erreur || "Le service ne répond pas (erreur " + reponse.status + ").");
          return donnees;
        });
      })
      .then(afficher)
      .catch(function (e) {
        etat.textContent = "";
        erreur.textContent = e.name === "AbortError"
          ? "La recherche a pris trop de temps. Réessayez ou saisissez le remplaçant vous-même."
          : "Suggestions impossibles : " + e.message + " Vous pouvez saisir le remplaçant vous-même.";
      })
      .finally(function () {
        clearTimeout(minuteur);
        bouton.disabled = false;
        bouton.removeAttribute("aria-busy");
      });
  });
})();
