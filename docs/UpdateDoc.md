# AWM Update Script

Script permettant de **mettre à jour une installation AWM existante** à partir d’une version plus récente du projet.

Le script copie les nouveaux fichiers tout en **préservant les éléments spécifiques à l'installation** (base de données, médias, environnement).

---

# Objectif

Mettre à jour un projet AWM existant sans :

- casser la configuration locale
- supprimer la base de données
- modifier l’environnement Python existant

---

# Prérequis

Avant d'utiliser le script :

- Python **3.9** installé
- Une installation **AWM existante fonctionnelle**
- Une **version plus récente du projet AWM**
- Les services IIS peuvent rester actifs (aucun arrêt obligatoire)

---

# Fichiers et dossiers protégés

Les éléments suivants **ne seront jamais modifiés** pendant la mise à jour :

```
venv/
logs/
.env
web/db/
web/src/media/
```

Cela permet de conserver :

- l’environnement Python
- les variables d’environnement
- la base de données
- les fichiers médias utilisateurs

---

# Utilisation

Lancer le script :

```bash
py update.py
```

Le script demandera :

```
Chemin du dossier AWM récent (source)
Chemin du dossier AWM existant (cible)
```

Exemple :

```
AWM récent : D:\Dev\AWM_NEW
AWM existant : C:\AWM
```

---

# Vérification de la connexion internet

Le script vérifie si une connexion internet est disponible.

Si **aucune connexion n'est détectée** :

```
Les librairies Python ne pourront pas être mises à jour.
Continuer ? (y/n)
```

L'utilisateur peut choisir de continuer ou d'annuler.

---

# Actions effectuées par le script

## 1️⃣ Mise à jour des fichiers

Copie des fichiers depuis le projet récent vers l'installation existante.

Les exclusions listées précédemment sont respectées.

---

## 2️⃣ Mise à jour de la venv (si internet)

Si internet est disponible :

```
pip install -r requirement.txt
```

Cela met à jour les dépendances Python.

---

## 3️⃣ Migrations Django

Le script exécute ensuite :

```
makemigrations
migrate --database=diagnostic_db
```

---

## 4️⃣ Mise à jour des fichiers statiques

```
collectstatic
```

Permet de mettre à jour les fichiers statiques utilisés par IIS.

---

# Résultat attendu

Après l'exécution :

- le projet est **mis à jour**
- la base de données est **conservée**
- la configuration `.env` est **inchangée**
- la venv est **mise à jour si internet disponible**

---

# Exemple de déroulement

```
AWM - Update d'un projet existant

Internet : OK

----- SYNCHRO FICHIERS -----
Copie / mise à jour en cours...
OK

----- POST-UPDATE -----
Mise à jour venv
makemigrations
migrate
collectstatic

Update terminé
```

---

# Bonnes pratiques

Avant une mise à jour :

- vérifier que l’application fonctionne
- sauvegarder la base de données et les **recettes** (optionnel mais recommandé)

---

# Résumé

Le script **automatise la mise à jour AWM** en :

- conservant les données critiques
- mettant à jour les fichiers du projet
- appliquant automatiquement les migrations
- mettant à jour les dépendances Python si possible
