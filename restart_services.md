# AWM Restart Services

Script permettant **d’arrêter puis redémarrer automatiquement les services COM AWM**.

Les services concernés sont :

```
AWM_COM_APPS_1
AWM_COM_APPS_2
AWM_COM_APPS_3
AWM_COM_APPS_4
AWM_COM_APPS_5

AWM_COM_RECIPE_1
AWM_COM_RECIPE_2
AWM_COM_RECIPE_3
AWM_COM_RECIPE_4
AWM_COM_RECIPE_5
```

Le script arrête tous les services puis les redémarre.

---

# Prérequis

- Windows
- Python **3.9+**
- Droits **Administrateur**
- Les services AWM doivent déjà être installés
- **NSSM** installé dans :

```
C:\nssm\nssm.exe
```

Si NSSM n'est pas détecté, le script utilise **sc.exe** automatiquement.

---

# Utilisation

Ouvrir **PowerShell ou CMD en administrateur**.

Lancer :

```bash
py restart_services.py
```

---

# Options disponibles

### Spécifier le chemin NSSM

```bash
py restart_services.py --nssm "C:\nssm\nssm.exe"
```

---

### Modifier le nombre de COM

Par défaut le script gère **5 COM**.

```bash
py restart_services.py --count 5
```

---

### Désactiver l'attente de statut

Par défaut le script attend que chaque service soit réellement arrêté/démarré.

Pour désactiver cette vérification :

```bash
py restart_services.py --no-wait
```

---

# Fonctionnement du script

## 1️⃣ Détection NSSM

Le script tente de détecter automatiquement :

```
C:\nssm\nssm.exe
C:\tools\nssm\nssm.exe
```

Sinon il utilise :

```
sc.exe
```

---

## 2️⃣ Arrêt des services

Les services suivants sont arrêtés :

```
AWM_COM_APPS_1..5
AWM_COM_RECIPE_1..5
```

Le script vérifie ensuite que l'état devient :

```
SERVICE_STOPPED
```

---

## 3️⃣ Redémarrage des services

Une fois arrêtés, les services sont redémarrés.

Le script vérifie l'état :

```
SERVICE_RUNNING
```

---

# Exemple d'exécution

```
NSSM détecté : C:\nssm\nssm.exe

----- STOP -----
AWM_COM_APPS_1
stopped

AWM_COM_APPS_2
stopped

...

----- START -----
AWM_COM_APPS_1
running

AWM_COM_APPS_2
running

...

Terminé
```

---

# Dépannage

### Timeout lors de l'arrêt

Si un service met du temps à s'arrêter, le script affiche :

```
timeout
```

Le statut réel du service est alors affiché pour diagnostic.

---

# Résumé

Ce script permet de :

- arrêter tous les services COM AWM
- redémarrer les services
- vérifier leur état
- fonctionner avec **NSSM**
