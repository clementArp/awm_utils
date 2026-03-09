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

Je te propose d’ajouter une petite section **après "Vérifier les services Windows"** pour expliquer la tâche planifiée. Voici un texte cohérent avec le style actuel de ta documentation.

---

# Tâche planifiée de nettoyage des logs

Une tâche planifiée Windows est automatiquement créée lors du déploiement afin de **nettoyer les anciens logs du projet**.

Cette tâche :

- parcourt le dossier :

```
C:\AWM\logs
```

- ainsi que **tous ses sous-dossiers** (ex : `IIS_APPS\W3SVC*`)
- supprime tous les fichiers **plus vieux que 14 jours**

---

## Nom de la tâche

La tâche créée suit le format :

```
AWM_LogCleanup_<ID_MACHINE>
```

Exemple pour la machine **ARP301** :

```
AWM_LogCleanup_301
```

---

## Planification

La tâche est configurée pour s’exécuter :

```
Tous les jours à 12:00
```

Elle exécute le script :

```
C:\AWM\cleanup_logs.ps1
```

---

## Vérifier dans le planificateur de tâches

1. Ouvrir **Planificateur de tâches** (`taskschd.msc`)
2. Aller dans :

```
Task Scheduler Library
```

3. Rechercher la tâche :

```
AWM_LogCleanup_<ID_MACHINE>
```

4. Vérifier que l’état est :

```
Ready
```

---

## Vérifier via ligne de commande

Il est également possible de vérifier la présence de la tâche avec :

```bash
schtasks /query | findstr AWM_LogCleanup
```

---

## Test manuel

Le script peut être exécuté manuellement avec :

```bash
powershell -ExecutionPolicy Bypass -File C:\AWM\cleanup_logs.ps1
```

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
