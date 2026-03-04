---

# ✅ CHECKLIST INSTALLATION AWM – USINE

📂 Les installateurs sont disponibles ici :

```
Z:\Electrique\developpement\arp_web_machine\Logiciels
```

Fichiers nécessaires :

- `python-3.9.1-amd64.exe`
- `mysql-installer-community-8.0.35.0.msi`
- `nssm.exe`
- `httpPlatformHandler_amd64.msi`

---

# 🟢 Résumé Ultra Rapide

1. Installer IIS (+ Initialisation applications)
2. Installer httpPlatformHandler
3. Installer MySQL (Custom + mot de passe arp360arp360)
4. Installer Python 3.9 (Add to PATH)
5. Donner droits IIS_IUSRS à Python39
6. Copier nssm.exe dans C:\nssm
7. Lancer le script

---

# 1️⃣ Installer IIS

## Activer IIS

1. Ouvrir **Panneau de configuration**

2. Aller dans **Programmes > Activer ou désactiver des fonctionnalités Windows**

3. Cocher :
   - Service World Wild / Internet Information Services / Fonctionnalités de développement d’applications / ✅ **Initialisation d’applications**

4. Cliquer **OK**

---

## Installer httpPlatformHandler

1. Lancer :

   ```
   httpPlatformHandler_amd64.msi
   ```

2. Installer normalement (Next → Finish)

---

# 2️⃣ Installer MySQL

Lancer :

```
mysql-installer-community-8.0.35.0.msi
```

### Configuration :

### Setup Type

- Choisir : **Custom**

### Sélectionner :

- ✅ Server
- ✅ Workbench
- ✅ Shell

Cliquer **Next → Execute**

---

### Type and Networking

- Choisir : **Server Computer**
- Next

---

### Authentication

- Choisir : **Use Strong Password Encryption**
- Next

---

### Configurer root

- User : `root`
- Mot de passe :

  ```
  arp360arp360
  ```

---

### Ajouter un utilisateur

Cliquer **Add User**

- User Name : `arp`
- Host : `localhost`
- Role : `DB Admin`
- Mot de passe :

  ```
  arp360arp360
  ```

Next

---

### Windows Service

- Laisser par défaut
- Next

---

### Server File Permissions

- Laisser :

  ```
  Yes, grant full access […]
  ```

- Cliquer **Execute**
- Puis **Next**
- Décocher :
  - Launch MySQL Workbench
  - Launch MySQL Shell

- Cliquer **Finish**

---

# 3️⃣ Installer Python 3.9

Lancer :

```
python-3.9.1-amd64.exe
```

### IMPORTANT

✅ Cocher :

```
Add Python 3.9 to PATH
```

Puis cliquer :

```
Install Now
```

À la fin :

- Cliquer sur **Disable Path Limit** si proposé

---

# 4️⃣ Donner les droits IIS sur Python

⚠️ Obligatoire si Python est installé en mode utilisateur.

1. Appuyer sur `Windows + R`
2. Taper :

```
%localappdata%\Programs\Python
```

3. Clic droit sur **Python39**
4. Propriétés → Sécurité → Modifier → Ajouter

---

### Ajouter le groupe IIS

1. Dans "Entrez les noms…", taper :

```
IIS_IUSRS
```

2. Cliquer sur **Vérifier les noms**
3. Valider
4. Donner **Contrôle total**
5. Appliquer

---

# 5️⃣ NSSM

Copier `nssm.exe` dans :

```
C:\nssm\
```

(Créer le dossier si nécessaire)

Vérifier :

```
C:\nssm\nssm.exe
```

---

# 6️⃣ Vérifications rapides

Dans PowerShell :

```bash
python --version
```

→ Doit afficher **Python 3.9.x**

```bash
mysql --version
```

→ Doit afficher version 8.0.x

---

# 7️⃣ Lancer le déploiement

Ouvrir PowerShell en mode administrateur.

Se placer dans le dossier du script :

```bash
py deploy_v3.py
```

Suivre les instructions à l’écran.

---

# 🎯 Résultat attendu

Après installation :

- IIS configuré
- Base de données créée
- Services Windows créés
- Applications accessibles :

```
http://localhost:8000 + XXX/
http://localhost:9000 + XXX/
```

---

# 🔎 En cas de problème

Vérifier :

- Droits administrateur
- MySQL démarré
- Dossier `C:\nssm\` présent
- Module httpPlatformHandler installé
