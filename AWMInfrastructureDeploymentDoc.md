---

# AWM Deployment Script

Script de déploiement automatique pour les applications **AWM APPS** et **AWM RECIPE**.

Ce script configure entièrement :

- Environnement Python
- Base de données MySQL
- IIS (Sites + AppPools + Handlers)
- Services Windows COM via NSSM
- Logs et rotation automatique

Le script est **idempotent** : il peut être relancé sans intervention manuelle.

---

# 📋 Prérequis

## Système

- Windows Server / Windows avec IIS
- Droits administrateur
- IIS installé
- Module **httpPlatformHandler**
- IIS Application Initialization activé

## Logiciels

- Python **3.9.x**
- MySQL installé et accessible (`mysql.exe`)
- NSSM installé dans :

```
C:\nssm\nssm.exe
```

## Réseau

- Accès à `pypi.org:443`
- MySQL accessible sur `127.0.0.1:3306`

---

# 🚀 Utilisation

## 1️⃣ Lancer en administrateur

Ouvrir PowerShell ou CMD en mode administrateur :

```bash
py deploy_v3.py
```

---

## 2️⃣ Paramètres demandés

Le script demandera :

- Chemin du projet source AWM
- Numéro machine (ex: 213)
- Dossier cible (ex: `C:\AWM`)
- Langues recettes (FR, EN, ES, DE, GR)
- ALLOWED_IPS

---

# ⚙️ Actions effectuées

## 📁 Projet

- Copie du projet vers le dossier cible
- Patch du `web.config`
- Mise à jour `.env`
- Création du venv Python
- Installation des dépendances

---

## 🗄 Base de données

- Création DB :

  ```
  arp_web_machine_<ID>
  ```

- Import du dump SQL
- Exécution des migrations Django

---

## 🌐 IIS

Création automatique :

- AppPool `AWM<ID>_APPS_POOL`
- AppPool `AWM<ID>_RECIPE_POOL`
- Site `AWM<ID>_APPS`
- Site `AWM<ID>_RECIPE`
- Configuration du handler `httpPlatformHandler`
- Virtual directories `static` et `media`
- Activation des logs IIS

Redémarrage automatique des AppPools.

---

## 🔁 Services COM (NSSM)

Création de 10 services :

### APPS

```
AWM_COM_APPS_1 → AWM_COM_APPS_5
```

### RECIPE

```
AWM_COM_RECIPE_1 → AWM_COM_RECIPE_5
```

Chaque service :

- Exécute Python en mode unbuffered (`-u`)
- A un redémarrage automatique (5s)
- A ses propres logs :

  ```
  logs/comX_apps_out.txt
  logs/comX_apps_err.txt
  logs/comX_recipe_out.txt
  logs/comX_recipe_err.txt
  ```

- Rotation activée à 100MB
- Variable d’environnement :

  ```
  COM_NUM = 1 à 5
  ```

---

# 🔄 Relance du script

Si les services existent déjà :

- Ils sont arrêtés
- Supprimés
- Recréés proprement
- Redémarrés automatiquement

Aucune action manuelle requise.

---

# 🌍 Accès aux applications

Après déploiement :

```
APPS   : http://localhost:8000 + <ID>/
RECIPE : http://localhost:9000 + <ID>/
```

---

# 🛠 Dépannage

Vérifier :

- `C:\nssm\nssm.exe` existe
- MySQL actif
- Droits administrateur
- Ports IIS disponibles

Consulter :

- `logs/comX_*.txt`
- `logs/IIS_*`

---

# 📌 Résumé

Ce script automatise :

✔ Installation Python
✔ Configuration MySQL
✔ Configuration IIS
✔ Création services Windows
✔ Démarrage automatique

---
