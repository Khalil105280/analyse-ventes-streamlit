from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Ventes autour des fêtes", layout="wide")

DATA_DIR = Path(__file__).resolve().parent


@st.cache_data
def charger():
    """Charge les ventes, le calendrier et les magasins ; retire les lignes incomplètes."""
    try:
        v = pd.read_csv(DATA_DIR / "ventes_journalieres.csv",
                        parse_dates=["date"], encoding="utf-8-sig")
        c = pd.read_csv(DATA_DIR / "calendrier_evenements.csv",
                        parse_dates=["date_debut", "date_fin"], encoding="utf-8-sig")
        m = pd.read_csv(DATA_DIR / "magasins.csv", encoding="utf-8-sig")
    except FileNotFoundError as e:
        st.error(f"Erreur de chargement de fichier : {e}. Assurez-vous que les fichiers CSV sont dans le bon répertoire.")
        st.stop() # Arrête l'exécution du script Streamlit si les fichiers ne sont pas trouvés

    required_columns = {
        "ventes": (v, {"date", "quantite", "categorie", "magasin_id"}),
        "calendrier": (c, {"evenement", "date_debut"}),
        "magasins": (m, {"magasin_id", "ville"}),
    }
    for name, (df, expected) in required_columns.items():
        missing = expected.difference(df.columns)
        if missing:
            raise ValueError(
                f"Colonnes manquantes dans {name} : {sorted(missing)}"
            )

    # Les fenêtres de l'application sont alignées sur le premier jour de l'événement.
    # Utiliser la date_debut pour aligner les événements.
    c["date"] = c["date_debut"]
    c["evenement"] = c["evenement"].str.strip().str.lower()
    v = v.dropna(subset=["date", "quantite", "categorie", "magasin_id"])
    v = v[v["quantite"] >= 0] # Assure que la quantité est non négative
    # Fusionner avec les informations des magasins pour obtenir la ville
    m_filtered = m[["magasin_id", "ville"]].drop_duplicates("magasin_id")
    v = v.merge(m_filtered,
                on="magasin_id", how="left")
    return v, c


# Charger les données
ventes, cal = charger()
st.title("Ventes autour des fêtes, alignées sur J0")

# Choix de l'utilisateur dans la barre latérale
# S'assurer que les listes de sélection ne sont pas vides pour éviter les erreurs
event_options = sorted(cal["evenement"].unique()) if not cal.empty else []
ville_options = ["Toutes"] + sorted(ventes["ville"].dropna().unique()) if not ventes.empty else ["Toutes"]
categorie_options = sorted(ventes["categorie"].unique()) if not ventes.empty else []

fete = st.sidebar.selectbox("Fête", event_options)
ville = st.sidebar.selectbox("Ville", ville_options)
categorie = st.sidebar.selectbox("Catégorie", categorie_options)
amplitude = st.sidebar.slider("Amplitude (jours)", 7, 60, 14)

# Filtrage des données basé sur les sélections de l'utilisateur
v_filtered = ventes.copy() # Utiliser une copie pour éviter les modifications sur le dataframe original
if categorie: # Vérifier si categorie est sélectionnable
    v_filtered = v_filtered[v_filtered["categorie"] == categorie]
if ville != "Toutes":
    v_filtered = v_filtered[v_filtered["ville"] == ville]

# Calculer les ventes journalières agrégées pour la période et la catégorie/ville sélectionnées
ventes_jour = v_filtered.groupby("date", as_index=False)["quantite"].sum()

# Alignement : pour chaque occurrence J0, fenêtre [J0 - A, J0 + A]
lignes = []
# S'assurer que fete est dans le calendrier avant de filtrer
if fete and not cal.empty and fete in cal["evenement"].unique():
    event_dates = cal.loc[cal["evenement"] == fete, "date"]
    for j0 in event_dates:
        # Filtrer les ventes_jour dans la fenêtre d'amplitude autour de j0
        fen = ventes_jour[
            ventes_jour["date"].between(
                j0 - pd.Timedelta(days=amplitude),
                j0 + pd.Timedelta(days=amplitude)
            )
        ].copy() # Utiliser .copy() pour éviter SettingWithCopyWarning
        if not fen.empty:
            fen["J"] = (fen["date"] - j0).dt.days
            fen["annee"] = j0.year
            lignes.append(fen)

# Affichage des résultats
if not lignes:
    st.warning("Aucune donnée de vente trouvée pour cette sélection d'événement, catégorie et ville.")
else:
    df_plot = pd.concat(lignes, ignore_index=True)
    # Agrégation par année et par jour relatif (J)
    # Assure que 'annee' est traitée comme une catégorie pour le coloriage
    agg = df_plot.groupby(["annee", "J"], as_index=False)["quantite"].sum()
    agg["annee"] = agg["annee"].astype(str) # Convertir en string pour un coloriage correct dans Plotly Express

    # Création du graphique en ligne
    fig = px.line(agg, x="J", y="quantite", color="annee",
                  title=f"Ventes autour de {fete} pour {categorie} dans {ville}")
    fig.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="J0", annotation_position="top left")
    fig.update_layout(xaxis_title="Jours relatifs à J0", yaxis_title="Quantité Vendue")
    st.plotly_chart(fig, use_container_width=True)

    # Affichage du dataframe agrégé sous forme de tableau pivot
    # Assure que toutes les valeurs sont numériques pour le pivot
    try:
        pivot_data = agg.pivot(index="J", columns="annee", values="quantite")
        st.dataframe(pivot_data)
    except Exception as e:
        st.error(f"Erreur lors de la création du tableau pivot : {e}")
