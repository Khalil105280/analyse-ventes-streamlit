"""
verification_m03.py
-------------------
Vérifications automatiques de l'absence de données du magasin M03 (5-12 mars 2021).

Contrôles :
  1. Localisation : le trou est-il propre à M03 ou partagé par sa région ?
  2. Reprise      : les ventes reprennent-elles après le 12 mars, et à quel niveau ?
  3. Catégories   : l'absence touche-t-elle toutes les catégories ou seulement certaines ?
  4. Historique   : la même fenêtre calendaire est-elle vide les autres années ?

Entrées attendues (colonnes du TP4) :
  - ventes  : DataFrame après dédoublonnage, avec date, magasin_id, categorie,
              chiffre_affaires_fcfa. À lancer AVANT l'exclusion des lignes
              sans quantité ni CA, sinon ces lignes apparaîtront comme des trous.
  - magasins : DataFrame issu de magasins.csv (magasin_id, ville, region)
"""

import pandas as pd

# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------
MAGASIN = "M03"
DEBUT_TROU = pd.Timestamp("2021-03-05")
FIN_TROU = pd.Timestamp("2021-03-12")
FENETRE = 14                 # jours avant/après utilisés pour comparer les niveaux
SEUIL_VOISIN_ACTIF = 0.90    # taux de jours couverts au-delà duquel un voisin est "normal"
SEUIL_VOISIN_ABSENT = 0.50   # taux en dessous duquel un voisin est "absent"
SEUIL_REBOND = 1.25          # ratio après/avant au-delà duquel on parle de rattrapage
SEUIL_BAISSE = 0.80          # ratio après/avant en dessous duquel on parle de baisse durable


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def _nb_jours(debut, fin):
    """Nombre de jours calendaires inclus entre debut et fin."""
    return (fin - debut).days + 1


def _couverture(ventes, magasins_ids, debut, fin):
    """Taux de jours de la période où chaque magasin a au moins une ligne de vente."""
    periode = ventes[(ventes["date"] >= debut) & (ventes["date"] <= fin)]
    jours_actifs = periode.groupby("magasin_id")["date"].nunique() / _nb_jours(debut, fin)
    # reindex : un magasin sans aucune ligne reçoit 0 au lieu de disparaître
    return jours_actifs.reindex(list(magasins_ids), fill_value=0.0)


# ---------------------------------------------------------------------------
# Contrôle 1 : localisation
# ---------------------------------------------------------------------------
def controle_localisation(ventes, magasins, magasin=MAGASIN,
                          debut=DEBUT_TROU, fin=FIN_TROU):
    """
    Le trou est-il propre au magasin, ou partagé par les autres magasins de sa région ?

    Verdicts :
      LOCAL            : les voisins vendent normalement -> problème propre à M03
      REGIONAL         : les voisins n'ont pas non plus de données -> événement régional possible
      MIXTE            : situation intermédiaire, à examiner jour par jour
      NON_DETERMINABLE : aucun autre magasin dans la même région
    """
    info = magasins.loc[magasins["magasin_id"] == magasin]
    if info.empty:
        raise ValueError(f"{magasin} absent de magasins.csv")
    region = info["region"].iat[0]
    ville = info["ville"].iat[0]

    voisins = magasins.loc[
        (magasins["region"] == region) & (magasins["magasin_id"] != magasin),
        "magasin_id",
    ].tolist()

    couv = _couverture(ventes, [magasin] + voisins, debut, fin)
    couv_voisins = couv.drop(magasin, errors="ignore")

    if couv_voisins.empty:
        verdict = "NON_DETERMINABLE"
    elif (couv_voisins >= SEUIL_VOISIN_ACTIF).all():
        verdict = "LOCAL"
    elif (couv_voisins < SEUIL_VOISIN_ABSENT).all():
        verdict = "REGIONAL"
    else:
        verdict = "MIXTE"

    return {
        "verdict": verdict,
        "ville": ville,
        "region": region,
        "couverture_magasin": round(float(couv.get(magasin, 0.0)), 2),
        "couverture_voisins": couv_voisins.round(2).to_dict(),
    }


# ---------------------------------------------------------------------------
# Contrôle 2 : reprise des ventes
# ---------------------------------------------------------------------------
def controle_reprise(ventes, magasin=MAGASIN, debut=DEBUT_TROU,
                     fin=FIN_TROU, fenetre=FENETRE):
    """
    Les ventes reprennent-elles après le trou, et à quel niveau par rapport à avant ?
    Le niveau = chiffre d'affaires moyen par jour où le magasin a effectivement vendu.
    """
    ca = (ventes[ventes["magasin_id"] == magasin]
          .groupby("date")["chiffre_affaires_fcfa"].sum())

    avant = ca[(ca.index >= debut - pd.Timedelta(days=fenetre)) & (ca.index < debut)]
    apres = ca[(ca.index > fin) & (ca.index <= fin + pd.Timedelta(days=fenetre))]
    apres_tout = ca[ca.index > fin]

    if apres_tout.empty:
        return {"verdict": "PAS_DE_REPRISE"}
    if avant.empty or apres.empty:
        return {"verdict": "NON_DETERMINABLE"}

    premier_jour = apres_tout.index.min()
    ratio = apres.mean() / avant.mean()

    if ratio > SEUIL_REBOND:
        verdict = "REBOND_POSSIBLE"
    elif ratio < SEUIL_BAISSE:
        verdict = "BAISSE_DURABLE"
    else:
        verdict = "REPRISE_NORMALE"

    return {
        "verdict": verdict,
        "premier_jour_apres_trou": premier_jour.date(),
        "ecart_jours": (premier_jour - fin).days,   # 1 = reprise dès le lendemain
        "ratio_apres_avant": round(float(ratio), 2),
    }


# ---------------------------------------------------------------------------
# Contrôle 3 : comparaison des catégories
# ---------------------------------------------------------------------------
def controle_categories(ventes, magasin=MAGASIN, debut=DEBUT_TROU,
                        fin=FIN_TROU, fenetre=FENETRE):
    """
    L'absence touche-t-elle toutes les catégories, ou seulement certaines ?

    Verdicts :
      ABSENCE_TOTALE    : aucune catégorie vendue -> fermeture ou saisie absente
      ABSENCE_PARTIELLE : certaines catégories manquent -> saisie incomplète probable
      PAS_D_ABSENCE     : toutes les catégories attendues sont présentes
      NON_DETERMINABLE  : pas de référence avant le trou
    """
    ref = ventes[(ventes["magasin_id"] == magasin) &
                 (ventes["date"] >= debut - pd.Timedelta(days=fenetre)) &
                 (ventes["date"] < debut)]
    cats_attendues = set(ref["categorie"].unique())

    trou = ventes[(ventes["magasin_id"] == magasin) &
                  (ventes["date"] >= debut) & (ventes["date"] <= fin)]
    cats_presentes = set(trou["categorie"].unique())
    cats_absentes = cats_attendues - cats_presentes

    # Catégories vendues par les autres magasins pendant la même période
    autres = ventes[(ventes["magasin_id"] != magasin) &
                    (ventes["date"] >= debut) & (ventes["date"] <= fin)]
    cats_vendues_ailleurs = set(autres["categorie"].unique())

    # Jours présents mais avec moins de catégories que d'habitude (saisie partielle)
    if ref.empty:
        jours_partiels = 0
    else:
        nb_cats_habituel = ref.groupby("date")["categorie"].nunique().median()
        nb_cats_jour = trou.groupby("date")["categorie"].nunique()
        jours_partiels = int((nb_cats_jour < nb_cats_habituel).sum())

    if not cats_attendues:
        verdict = "NON_DETERMINABLE"
    elif not cats_presentes:
        verdict = "ABSENCE_TOTALE"
    elif cats_absentes:
        verdict = "ABSENCE_PARTIELLE"
    else:
        verdict = "PAS_D_ABSENCE"

    return {
        "verdict": verdict,
        "nb_categories_attendues": len(cats_attendues),
        "categories_absentes": sorted(cats_absentes),
        "categories_absentes_vendues_ailleurs": sorted(cats_absentes & cats_vendues_ailleurs),
        "jours_avec_saisie_partielle": jours_partiels,
    }


# ---------------------------------------------------------------------------
# Contrôle 4 (complément) : même fenêtre, toutes années
# ---------------------------------------------------------------------------
def controle_historique(ventes, magasin=MAGASIN, debut=DEBUT_TROU, fin=FIN_TROU):
    """
    Nombre de jours sans données pour la même fenêtre calendaire, année par année.
    Si d'autres années présentent aussi des trous, le problème est probablement structurel.
    """
    jours_presents = pd.DatetimeIndex(
        ventes.loc[ventes["magasin_id"] == magasin, "date"].dt.normalize().unique()
    )
    manquants = {}
    for annee in sorted(ventes["date"].dt.year.unique()):
        annee = int(annee)
        fenetre_annee = pd.date_range(debut.replace(year=annee), fin.replace(year=annee))
        manquants[annee] = int((~fenetre_annee.isin(jours_presents)).sum())
    return manquants


# ---------------------------------------------------------------------------
# Synthèse
# ---------------------------------------------------------------------------
def conclure(r):
    """Traduit les verdicts en conclusion, sans trancher seul la cause."""
    autres_annees = [v for a, v in r["historique_jours_manquants"].items()
                     if a != DEBUT_TROU.year]
    if any(v > 0 for v in autres_annees):
        return ("Trous présents d'autres années : problème de données probablement "
                "structurel, pas un événement isolé.")

    loc = r["localisation"]["verdict"]
    if loc == "LOCAL":
        if r["categories"]["verdict"] == "ABSENCE_TOTALE":
            return ("Trou propre à M03 et touchant toutes les catégories : fermeture ou "
                    "absence de saisie, à vérifier auprès du responsable. L'événement "
                    "régional ne suffit pas à l'expliquer.")
        return ("Trou propre à M03 : l'événement régional ne suffit pas à l'expliquer, "
                "vérifier la saisie.")
    if loc == "REGIONAL":
        return ("Trou partagé par la région : l'hypothèse contextuelle gagne en "
                "crédibilité, à confirmer par une source.")
    return "Résultat intermédiaire : examiner les verdicts détaillés."


def verifier_m03(ventes, magasins):
    """Lance les quatre contrôles et renvoie un dictionnaire de résultats."""
    ventes = ventes.copy()
    ventes["date"] = pd.to_datetime(ventes["date"])

    resultats = {
        "localisation": controle_localisation(ventes, magasins),
        "reprise": controle_reprise(ventes),
        "categories": controle_categories(ventes),
        "historique_jours_manquants": controle_historique(ventes),
    }
    resultats["conclusion"] = conclure(resultats)
    return resultats


def afficher(r):
    """Affichage lisible du rapport de vérification."""
    print("=== Vérification M03 : 5-12 mars 2021 ===")

    loc = r["localisation"]
    print(f"1. Localisation : {loc['verdict']} ({loc['ville']}, région {loc['region']})")
    print(f"   couverture M03 : {loc['couverture_magasin']}")
    print(f"   couverture voisins : {loc['couverture_voisins']}")

    rep = r["reprise"]
    details = {k: v for k, v in rep.items() if k != "verdict"}
    print(f"2. Reprise : {rep['verdict']} {details}")

    cat = r["categories"]
    print(f"3. Catégories : {cat['verdict']}")
    print(f"   absentes : {cat['categories_absentes']}")
    print(f"   absentes mais vendues ailleurs : {cat['categories_absentes_vendues_ailleurs']}")
    print(f"   jours avec saisie partielle : {cat['jours_avec_saisie_partielle']}")

    print(f"4. Jours manquants par année : {r['historique_jours_manquants']}")
    print(f"Conclusion : {r['conclusion']}")


if __name__ == "__main__":
    # Exemple : à remplacer par le DataFrame nettoyé du script principal
    ventes = pd.read_csv("ventes_journalieres.csv", parse_dates=["date"])
    magasins = pd.read_csv("magasins.csv")
    afficher(verifier_m03(ventes, magasins))
