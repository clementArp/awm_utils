#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Déploiement AWM sous IIS (httpPlatformHandler)

Objectif de cette version:
- Ne pas changer le fonctionnement (mêmes étapes, mêmes commandes).
- Rendre la sortie console plus "digest" (moins de flood), tout en gardant
  un log complet disponible via fichier + mode --verbose.

Usage:
  py deploy.py
  py deploy.py --verbose
  py deploy.py --log D:\temp\deploy_awmlog.txt
"""

import argparse
import time
import datetime as _dt
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union


# =========================
# Paramètres faciles à changer (inchangés)
# =========================
DEFAULT_TARGET_DIR = r"C:\AWM"
PY_LAUNCHER = "py"
PY_VERSION_FLAG = "-3.9"

PORT_APPS_BASE = 8000
PORT_RECIPE_BASE = 9000

SITE_SUFFIX_APPS = "_APPS"
SITE_SUFFIX_RECIPE = "_RECIPE"

HANDLER_NAME = "AWMHandler"
HANDLER_MODULE = "httpPlatformHandler"
VIRTUAL_STATIC_NAME = "static"
VIRTUAL_MEDIA_NAME = "media"
SITE_PREFIX = "AWM"  # pour les noms de sites IIS : AWM{num}...

REL_MANAGE_PY = r"web\src\manage.py"
REL_STATIC_COLLECTED = r"web\src\collected_static"
REL_MEDIA_DIR = r"web\src\media"
REQUIREMENTS_FILE = "requirement.txt"  # chez toi c'est "requirement.txt" (singulier)

# Migration command spécifique
MIGRATE_DB_NAME = "diagnostic_db"

# MySQL
MYSQL_USER = "root"
MYSQL_PASSWORD = "arp360arp360"
MYSQL_HOST = "127.0.0.1"
MYSQL_PORT = "3306"
MYSQL_BIN_FALLBACK = r"C:\Program Files\MySQL\MySQL Server 8.0\bin"

# NSSM (services Windows)
# Exigence: nssm.exe présent sur le disque C: (ou dans PATH). On tente d'abord PATH,
# puis quelques emplacements usuels sur C:\.
NSSM_CANDIDATES = [
    r"C:\nssm.exe",
    r"C:\nssm\nssm.exe",
    r"C:\tools\nssm.exe",
    r"C:\tools\nssm\nssm.exe",
    r"C:\Utilities\nssm.exe",
    r"C:\Utilities\nssm\nssm.exe",
]

COM_SERVICE_COUNT = 5  # AWM_COM_(APPS|RECIPE)_1..5
COM_LOG_ROTATE_BYTES = 100_000_000
COM_RESTART_DELAY_MS = 5000


def find_nssm() -> Optional[str]:
    """
    Retourne le chemin vers nssm.exe si trouvé, sinon None.
    """
    # 1) PATH
    p = shutil.which("nssm")
    if p and Path(p).exists():
        return str(Path(p))

    # 2) Emplacements usuels sur C:\
    for cand in NSSM_CANDIDATES:
        if Path(cand).exists():
            return cand

    return None


def check_nssm_present() -> tuple[bool, str]:
    p = find_nssm()
    return (p is not None), (p or "")


# =========================
# Logging "digest"
# =========================
@dataclass
class CmdResult:
    cmd: Union[str, Sequence[str]]
    returncode: int
    stdout: str
    stderr: str


class Logger:
    def __init__(self, *, verbose: bool, log_file: Optional[Path]):
        self.verbose = verbose
        self.log_file = log_file
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _write_file(self, msg: str) -> None:
        if not self.log_file:
            return
        with self.log_file.open("a", encoding="utf-8", errors="replace") as f:
            f.write(msg)

    def info(self, msg: str) -> None:
        print(msg)
        self._write_file(msg + "\n")

    def section(self, title: str) -> None:
        bar = "-" * max(10, len(title))
        self.info(f"\n{bar}\n{title}\n{bar}")

    def cmdline(self, cmd: Union[str, Sequence[str]]) -> None:
        if isinstance(cmd, str):
            s = cmd
        else:
            s = " ".join(cmd)
        self.info(f"\n> {s}")

    def cmd_output(self, stdout: str, stderr: str, *, mode: str) -> None:
        """
        mode:
          - "full": afficher tout
          - "tail": n'afficher que la fin (console), garder tout dans log file
          - "quiet": n'afficher presque rien (console), garder tout dans log file
        """
        # Toujours écrire le complet dans le fichier
        if (stdout or stderr) and self.log_file:
            if stdout:
                self._write_file(stdout if stdout.endswith("\n") else stdout + "\n")
            if stderr:
                self._write_file(stderr if stderr.endswith("\n") else stderr + "\n")

        if self.verbose or mode == "full":
            if stdout:
                print(stdout)
            if stderr:
                print(stderr, file=sys.stderr)
            return

        if mode == "quiet":
            # rien en console (ou presque)
            # On évite d'avoir un silence total: si stderr existe -> tail
            if stderr:
                tail = "\n".join(stderr.splitlines()[-10:])
                if tail.strip():
                    print("\n[stderr]\n" + tail, file=sys.stderr)
            return

        # mode == "tail"
        if stdout:
            tail = "\n".join(stdout.splitlines()[-12:])
            if tail.strip():
                print(tail)
        if stderr:
            tail = "\n".join(stderr.splitlines()[-12:])
            if tail.strip():
                print("\n[stderr]\n" + tail, file=sys.stderr)


# Logger global (initialisé dans main)
LOG: Logger


def _default_log_path() -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / f"deploy_awm_{ts}.log"


def _classify_cmd_for_console(cmd: Union[str, Sequence[str]]) -> str:
    """
    Détermine à quel point c'est verbeux; sans changer la commande elle-même.
    """
    s = cmd if isinstance(cmd, str) else " ".join(cmd)
    s_low = s.lower()

    if " pip.exe install " in s_low or (" -m pip " in s_low and " install " in s_low):
        return "quiet"  # pip spam énormément
    if " collectstatic" in s_low:
        return "tail"
    if " powershell " in s_low:
        # Le script PowerShell IIS est très long; on affiche la fin seulement
        return "tail"
    return "tail"


def run(
    cmd: Sequence[str],
    cwd: Optional[str] = None,
    check: bool = True,
    *,
    show_cmd: bool = True,
    mode_override: Optional[str] = None,  # "full" | "tail" | "quiet"
) -> CmdResult:
    if show_cmd:
        LOG.cmdline(cmd)

    p = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )

    mode = mode_override or ("full" if LOG.verbose else _classify_cmd_for_console(cmd))
    LOG.cmd_output(p.stdout or "", p.stderr or "", mode=mode)

    if check and p.returncode != 0:
        raise RuntimeError(f"Commande échouée ({p.returncode}): {' '.join(cmd)}")

    return CmdResult(cmd=cmd, returncode=p.returncode, stdout=p.stdout or "", stderr=p.stderr or "")


def powershell(ps_script: str, check: bool = True) -> CmdResult:
    wrapped = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "$OutputEncoding = [Console]::OutputEncoding; " + ps_script
    )
    return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapped], check=check)


def is_admin() -> bool:
    try:
        import ctypes

        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def ask(prompt: str, default: Optional[str] = None) -> str:
    if default is None:
        return input(prompt).strip()
    s = input(f"{prompt} [{default}] ").strip()
    return s if s else default


def check_python39() -> bool:
    try:
        p = run([PY_LAUNCHER, PY_VERSION_FLAG, "-V"], check=True)
        return "Python 3.9" in (p.stdout + p.stderr)
    except Exception:
        return False


def check_mysql_installed() -> bool:
    return get_mysql_exe() is not None


def check_internet_access(host: str = "pypi.org", port: int = 443, timeout: int = 3) -> bool:
    """Test simple: socket vers pypi.org:443 (utile pour pip install)."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_iis_application_init_enabled() -> bool:
    """
    Vérifie la feature Windows:
    IIS -> World Wide Web Services -> Application Development Features -> Application Initialization
    FeatureName DISM: IIS-ApplicationInit
    """
    ps = r"(Get-WindowsOptionalFeature -Online -FeatureName IIS-ApplicationInit).State"
    p = powershell(ps, check=False)
    out = (p.stdout or "") + (p.stderr or "")
    return "Enabled" in out


def check_httpplatformhandler_installed() -> bool:
    """Vérifie que le module global IIS 'httpPlatformHandler' est installé."""
    ps = r"Import-Module WebAdministration; (Get-WebGlobalModule | Where-Object {$_.Name -eq 'httpPlatformHandler'} | Measure-Object).Count"
    p = powershell(ps, check=False)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    nums = re.findall(r"\d+", out)
    try:
        return int(nums[-1]) > 0
    except Exception:
        return False


def check_iis_iusrs_can_access_python39() -> tuple[bool, str]:
    """
    Best-effort: vérifie que 'IIS_IUSRS' apparaît dans les ACL du dossier Python (py -3.9).
    Retourne (ok, python_dir).
    """
    try:
        p = run([PY_LAUNCHER, PY_VERSION_FLAG, "-c", "import sys; print(sys.executable)"], check=True)
        pyexe = (p.stdout or "").strip().splitlines()[-1].strip()
        if not pyexe:
            return False, ""
        py_dir = str(Path(pyexe).parent)
        ic = subprocess.run(["icacls", py_dir], capture_output=True, text=True, encoding="utf-8", errors="replace")
        txt = (ic.stdout or "") + (ic.stderr or "")
        return ("IIS_IUSRS" in txt), py_dir
    except Exception:
        return False, ""


def check_prerequisites_or_exit() -> None:
    ok_appinit = check_iis_application_init_enabled()
    ok_httpplatform = check_httpplatformhandler_installed()
    ok_acl, py_dir = check_iis_iusrs_can_access_python39()
    ok_net = check_internet_access()

    LOG.section("PRÉREQUIS IIS / httpPlatformHandler")
    LOG.info(f"1) IIS Application Initialization (IIS-ApplicationInit) activé ? {ok_appinit}")
    LOG.info(f"2) Module IIS httpPlatformHandler installé ? {ok_httpplatform}")
    LOG.info(f"3) Droits IIS_IUSRS sur Python (dossier: {py_dir or 'N/A'}) ? {ok_acl}")
    LOG.info(f"4) Accès internet (pypi.org:443) ? {ok_net}")

    if ok_appinit and ok_httpplatform and ok_acl and ok_net:
        return

    LOG.info("\n❌ Pré-requis manquants. Actions à faire :")
    if not ok_appinit:
        LOG.info(
            " - Activer IIS -> World Wide Web Services -> Application Development Features -> Application Initialization"
        )
    if not ok_httpplatform:
        LOG.info(" - Installer httpPlatformHandler (ex: httpPlatformHandler_amd64.msi)")
    if not ok_acl:
        LOG.info(" - Donner les droits à IIS sur le dossier Python :")
        LOG.info("   1) Aller dans %localappdata%\\Programs\\Python")
        LOG.info("   2) Sécurité -> Modifier -> sélectionner le niveau le plus haut (USER) puis ajouter IIS_IUSRS")
        if py_dir:
            LOG.info(f"   (dossier python détecté: {py_dir})")
    if not ok_net:
        LOG.info(" - Vérifier l'accès internet (nécessaire pour pip install).")

    sys.exit(1)


def validate_machine_num(s: str) -> int:
    if not re.fullmatch(r"\d{3}", s):
        raise ValueError("Le numéro machine doit être sur 3 chiffres (ex: 105).")
    return int(s)


def copy_project(src: Path, dst: Path) -> None:
    if dst.exists():
        resp = ask(f"Le dossier cible existe déjà: {dst}\nÉcraser (supprime puis recopie) ? (y/n)", "n")
        if resp.lower() != "y":
            LOG.info("Copie annulée.")
            return
        safe_rmtree(dst)
    LOG.info(f"Copie du projet: {src} -> {dst}")
    shutil.copytree(src, dst)


def set_execution_policy_current_user() -> None:
    # Optionnel: en entreprise c'est souvent bloqué par GPO.
    # On tente, mais on ne bloque jamais le déploiement.
    try:
        run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force",
            ],
            check=False,
        )
    except Exception:
        pass


def get_mysql_exe() -> Optional[str]:
    p = shutil.which("mysql")
    if p:
        return p
    candidate = Path(MYSQL_BIN_FALLBACK) / "mysql.exe"
    return str(candidate) if candidate.exists() else None


def ensure_mysql_in_process_path() -> None:
    """Ajoute mysql au PATH uniquement pour CE script (pas permanent)."""
    if shutil.which("mysql"):
        return
    if Path(MYSQL_BIN_FALLBACK).exists():
        os.environ["PATH"] = MYSQL_BIN_FALLBACK + os.pathsep + os.environ.get("PATH", "")


def ensure_mysql_db_exists(
    db_name: str,
    host: str = MYSQL_HOST,
    port: str = MYSQL_PORT,
    user: str = MYSQL_USER,
    password: str = MYSQL_PASSWORD,
) -> bool:
    if not check_mysql_installed():
        LOG.info("(MySQL) mysql.exe introuvable -> impossible de créer la DB.")
        return False

    LOG.info(f"(MySQL) Création si absente: {db_name}")

    mysql = get_mysql_exe()
    if not mysql:
        LOG.info("(MySQL) mysql.exe introuvable -> impossible de créer la DB.")
        return False

    cmd = [
        mysql,
        f"-u{user}",
        f"-p{password}",
        f"-h{host}",
        f"-P{port}",
        "-e",
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
    ]
    p = run(cmd, check=False)
    if p.returncode == 0:
        LOG.info(f"(MySQL) OK : DB {db_name} prête.")
        return True

    LOG.info("(MySQL) Échec création DB (droits / mdp / service MySQL).")
    return False


def import_mysql_dump(
    root: Path,
    db_name: str,
    host: str = MYSQL_HOST,
    port: str = MYSQL_PORT,
    user: str = MYSQL_USER,
    password: str = MYSQL_PASSWORD,
) -> bool:
    try:
        dump_path = root / r"web\db\init\dumps.sql"
        if not os.path.exists(dump_path):
            raise RuntimeError(f"(MySQL) Dump non trouvé: {dump_path} -> skip.")
        LOG.info(f"(MySQL) Import dump: {dump_path} -> {db_name}")

        mysql = get_mysql_exe()
        if not mysql:
            LOG.info("(MySQL) mysql.exe introuvable -> impossible d'importer le dump.")
            return False

        cmd = [
            mysql,
            f"-u{user}",
            f"-p{password}",
            f"-h{host}",
            f"-P{port}",
            db_name,
        ]

        with open(dump_path, "rb") as dump:
            subprocess.run(cmd, stdin=dump, check=True)
        return True
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Process : (MySQL) Import dump échoué {e}).") from e
    except Exception as e:
        raise RuntimeError(f"(MySQL) Import dump échoué {e}).") from e


def create_venv_and_install(root: Path, machine_num: int, target_dir: Path) -> None:
    venv_dir = root / "venv"

    # venv
    run([PY_LAUNCHER, PY_VERSION_FLAG, "-m", "venv", "venv"], cwd=str(root))
    pip = str(venv_dir / "Scripts" / "pip.exe")
    py = str(venv_dir / "Scripts" / "python.exe")

    # pip install requirements (commande inchangée, sortie console compactée)
    req = root / REQUIREMENTS_FILE
    if not req.exists():
        raise FileNotFoundError(f"Fichier requirements introuvable: {req}")
    run([pip, "install", "-r", str(req)], cwd=str(root))

    # django commands
    manage = root / REL_MANAGE_PY
    if not manage.exists():
        raise FileNotFoundError(f"manage.py introuvable: {manage}")

    run([py, str(manage), "collectstatic", "--noinput"], cwd=str(root))
    run([py, str(manage), "makemigrations"], cwd=str(root))

    db_name = f"arp_web_machine_{machine_num:03d}"
    if not ensure_mysql_db_exists(db_name):
        raise RuntimeError(
            f"(MySQL) Impossible de créer/vérifier la base '{db_name}'. "
            "Corrige les identifiants MySQL (root/...) ou crée la DB manuellement, puis relance le script."
        )

    do_dump = ask("Importer le dump SQL dans la DB machine ? (y/n)", "y")
    if do_dump.lower() == "y":
        ensure_mysql_db_exists(db_name)
        import_mysql_dump(target_dir, db_name)

    run([py, str(manage), "migrate", "--database", MIGRATE_DB_NAME], cwd=str(root))


def update_env_after_copy(root: Path, machine_num: int) -> None:
    """
    Met à jour le fichier .env (après copie du projet) :
      - MACHINE_ID = <num machine sur 3 chiffres>
      - ALLOWED_IPS = "<ip1 ip2 ...>" (demande à l'utilisateur)
      - DEBUG = "False" (force à False si True)
    """
    env_file = root / ".env"
    if not env_file.exists():
        LOG.info("(.env) Non trouvé -> skip.")
        return

    lines = env_file.read_text(encoding="utf-8", errors="ignore").splitlines()

    def set_or_add(key: str, value: str) -> None:
        nonlocal lines
        pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for i, line in enumerate(lines):
            if pat.match(line):
                lines[i] = f"{key} = {value}"
                return
        lines.append(f"{key} = {value}")

    def get_value(key: str) -> Optional[str]:
        pat = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)\s*$")
        for line in lines:
            m = pat.match(line)
            if m:
                return m.group(1).strip()
        return None

    set_or_add("MACHINE_ID", f"{machine_num:03d}")

    current_allowed = get_value("ALLOWED_IPS") or '"127.0.0.1 localhost"'
    default_allowed = current_allowed.strip().strip('"').strip("'")
    allowed_ips = ask("ALLOWED_IPS (ex: 127.0.0.1 localhost 10.0.0.12) :", default_allowed)
    set_or_add("ALLOWED_IPS", f'"{allowed_ips}"')

    current_debug = (get_value("DEBUG") or "").strip()
    if current_debug.lower() in {'"true"', "true", "'true'"}:
        LOG.info('(.env) DEBUG était à True -> forcé à "False".')
    set_or_add("DEBUG", '"False"')

    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOG.info("(.env) Mis à jour : MACHINE_ID, ALLOWED_IPS, DEBUG.")


def patch_web_config_paths(root: Path, chosen_root: Path) -> None:
    r"""
    Remplace les occurrences de C:\AWM (hardcodées) par le chemin réellement choisi.
    (docstring raw pour éviter les SyntaxWarning sur les backslashes Windows)
    """
    web_config = root / "web.config"
    if not web_config.exists():
        LOG.info("(web.config) Non trouvé -> skip.")
        return

    old = r"C:\AWM"
    new = str(chosen_root)

    content = web_config.read_text(encoding="utf-8", errors="ignore")
    if old not in content:
        LOG.info(r"(web.config) Aucun 'C:\AWM' trouvé -> rien à patcher.")
        return

    web_config.write_text(content.replace(old, new), encoding="utf-8")
    LOG.info(f"(web.config) Patch OK : '{old}' -> '{new}'")


def configure_recipe_languages(root: Path) -> None:
    """
    Demande à l'utilisateur les langues à utiliser dans les recettes,
    et les écrit dans web\src\config.json.
    """
    cfg_path = root / r"web\src\config.json"
    if not cfg_path.exists():
        LOG.info("(config.json) Non trouvé -> skip.")
        return

    allowed = {"FR", "EN", "ES", "DE", "GR"}

    raw = ask("Langues recettes (séparées par des virgules) parmi FR,EN,ES,DE,GR", "FR,EN")
    langs = [x.strip().upper() for x in raw.split(",") if x.strip()]
    langs = [x for x in langs if x in allowed]

    if not langs:
        langs = ["FR", "EN"]
        LOG.info("(config.json) Aucune langue valide saisie -> fallback FR,EN")

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        data = {}
        LOG.info("(config.json) JSON invalide -> on repart de {}")

    data["langues"] = langs
    cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG.info(f"(config.json) Langues recettes = {langs}")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def service_exists(service: str) -> bool:
    """
    Retourne True si un service Windows existe déjà.
    Utilise sc.exe (présent par défaut).
    """
    r = subprocess.run(
        ["sc", "query", service],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        return False
    out = (r.stdout or "") + (r.stderr or "")
    return "SERVICE_NAME" in out or "STATE" in out


def nssm_configure_existing(nssm: str, service: str, app: str, args: str, app_dir: str) -> None:
    """
    Si le service existe, on force la configuration principale (équivalent à un 'install' + réglages).
    """
    # Chemin exe
    nssm_set(nssm, service, "Application", app)
    # Arguments (string)
    nssm_set(nssm, service, "AppParameters", args)
    # Startup directory
    nssm_set(nssm, service, "AppDirectory", app_dir)


def ensure_nssm_service(nssm: str, service: str, app: str, args: str, app_dir: str) -> None:
    """
    Installe le service via NSSM.

    ⚠️ Comportement demandé: si le service existe déjà, on le SUPPRIME puis on le recrée
    (pour repartir de zéro), au lieu de le mettre à jour.
    """
    if service_exists(service):
        LOG.info(f"🧹 Service déjà présent: {service} -> suppression puis recréation")

        # Stop (best effort)
        run_nssm([nssm, "stop", service], check=False)

        # Remove
        # "confirm" évite la demande interactive
        run_nssm([nssm, "remove", service, "confirm"], check=True)

        # Attendre qu'il disparaisse (pour éviter des races avec SCM)
        for _ in range(20):
            if not service_exists(service):
                break
            time.sleep(0.25)

    # Install (fresh)
    nssm_install(nssm, service, app, args, app_dir)


def run_nssm(cmd: Sequence[str], *, check: bool = True) -> CmdResult:
    return run(cmd, check=check, show_cmd=False, mode_override="quiet")


def nssm_set(nssm: str, service: str, key: str, value: str) -> None:
    # nssm set <service> <key> <value>
    run_nssm([nssm, "set", service, key, value], check=True)


def nssm_install(nssm: str, service: str, app: str, args: str, app_dir: str) -> None:
    # nssm install <service> <app> <args...>
    # On passe args comme une seule string après l'app (nssm attend le reste de la ligne comme arguments).
    # En list-subprocess, on fournit chaque token séparément.
    arg_tokens = args.split(" ") if args else []
    run_nssm([nssm, "install", service, app, *arg_tokens], check=True)
    nssm_set(nssm, service, "AppDirectory", app_dir)


def create_com_services(root: Path) -> None:
    """
    Crée 10 services via NSSM:
      - AWM_COM_RECIPE_1..5  (python -u com\main\recipe.py, COM_NUM=1..5)
      - AWM_COM_APPS_1..5    (python -u com\main\main.py,   COM_NUM=1..5)

    Configuration appliquée (alignée sur ton cahier des charges):
      - Application: <root>\venv\Scripts\python.exe
      - Startup directory: <root>\
      - Args: -u <root>\com\main\main.py  (APPS) / -u <root>\com\main\recipe.py (RECIPE)
      - Exit Actions: Restart delay 5000 ms
      - I/O: stdout/stderr dans <root>\logs\com{n}_apps|recipe_(out|err).txt
      - File Rotation: enabled + online + rotate bytes 100_000_000
      - Environment: COM_NUM = n
    """
    ok, nssm = check_nssm_present()
    if not ok:
        raise RuntimeError("nssm.exe introuvable (pré-requis).")

    root = Path(root)
    logs_dir = root / "logs"
    ensure_dir(logs_dir)

    py = root / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        raise FileNotFoundError(f"Python venv introuvable: {py}")

    apps_script = root / "com" / "main" / "main.py"
    recipe_script = root / "com" / "main" / "recipe.py"
    if not apps_script.exists():
        LOG.info(f"⚠️ Script APPS introuvable: {apps_script}")
    if not recipe_script.exists():
        LOG.info(f"⚠️ Script RECIPE introuvable: {recipe_script}")

    def configure_common(service: str, com_num: int, stdout_path: Path, stderr_path: Path) -> None:
        # Auto-start
        nssm_set(nssm, service, "Start", "SERVICE_AUTO_START")

        # Restart delay (Exit Actions -> Restart / delay)
        nssm_set(nssm, service, "AppRestartDelay", str(COM_RESTART_DELAY_MS))

        # I/O redirections
        nssm_set(nssm, service, "AppStdout", str(stdout_path))
        nssm_set(nssm, service, "AppStderr", str(stderr_path))

        # File rotation
        nssm_set(nssm, service, "AppRotateFiles", "1")
        nssm_set(nssm, service, "AppRotateOnline", "1")
        nssm_set(nssm, service, "AppRotateBytes", str(COM_LOG_ROTATE_BYTES))

        # Environment
        # NSSM accepte "KEY=VALUE" via AppEnvironmentExtra (multi-string). On pose COM_NUM.
        nssm_set(nssm, service, "AppEnvironmentExtra", f"COM_NUM={com_num}")

    LOG.section("SERVICES COM (NSSM)")
    for i in range(1, COM_SERVICE_COUNT + 1):
        # --- APPS
        svc_apps = f"AWM_COM_APPS_{i}"
        args_apps = f"-u {apps_script}"
        ensure_nssm_service(nssm, svc_apps, str(py), args_apps, str(root))
        configure_common(
            svc_apps,
            i,
            logs_dir / f"com{i}_apps_out.txt",
            logs_dir / f"com{i}_apps_err.txt",
        )
        LOG.info(f"✅ Service créé/configuré: {svc_apps} (COM_NUM={i})")

    for i in range(1, COM_SERVICE_COUNT + 1):
        # --- RECIPE
        svc_recipe = f"AWM_COM_RECIPE_{i}"
        args_recipe = f"-u {recipe_script}"
        ensure_nssm_service(nssm, svc_recipe, str(py), args_recipe, str(root))
        configure_common(
            svc_recipe,
            i,
            logs_dir / f"com{i}_recipe_out.txt",
            logs_dir / f"com{i}_recipe_err.txt",
        )
        LOG.info(f"✅ Service créé/configuré: {svc_recipe} (COM_NUM={i})")

    LOG.info("Services COM créés. (Démarrage automatique au boot)")

    # Démarrage immédiat (comme demandé)
    LOG.info("Démarrage des services COM...")
    for i in range(1, COM_SERVICE_COUNT + 1):
        for service in (f"AWM_COM_APPS_{i}", f"AWM_COM_RECIPE_{i}"):
            try:
                r = run_nssm([nssm, "start", service], check=False)
                if r.returncode == 0:
                    LOG.info(f"▶️  Service démarré: {service}")
                else:
                    LOG.info(f"⚠️  Service non démarré (code {r.returncode}): {service} (voir log pour détails)")
            except Exception as e:
                LOG.info(f"⚠️  Service non démarré: {service} ({e})")

    LOG.info("Services COM démarrés (ou tentative effectuée).")


def configure_iis_sites(root: Path, machine_num: int) -> None:
    port_apps = PORT_APPS_BASE + machine_num
    port_recipe = PORT_RECIPE_BASE + machine_num

    site_apps = f"{SITE_PREFIX}{machine_num:03d}{SITE_SUFFIX_APPS}"
    site_recipe = f"{SITE_PREFIX}{machine_num:03d}{SITE_SUFFIX_RECIPE}"

    static_path = root / REL_STATIC_COLLECTED
    media_path = root / REL_MEDIA_DIR

    if not static_path.exists():
        LOG.info(f"(IIS) Warning: static path introuvable: {static_path}")
    if not media_path.exists():
        LOG.info(f"(IIS) Warning: media path introuvable: {media_path}")

    # Script PowerShell IIS (identique fonctionnellement; suppression du doublon Restart-AppPool-Safe 1)
    ps = rf"""
Import-Module WebAdministration

function Ensure-AppPool($name) {{
  if (-not (Test-Path "IIS:\AppPools\$name")) {{
    New-WebAppPool -Name $name | Out-Null
  }}
  Set-ItemProperty "IIS:\AppPools\$name" -Name startMode -Value AlwaysRunning
  Set-ItemProperty "IIS:\AppPools\$name" -Name managedRuntimeVersion -Value ""
  Set-ItemProperty "IIS:\AppPools\$name" -Name processModel.idleTimeout -Value ([TimeSpan]::FromMinutes(0))
}}

function Ensure-Site($siteName, $appPoolName, $physicalPath, $port) {{
  if (-not (Test-Path "IIS:\Sites\$siteName")) {{
    New-Website -Name $siteName -PhysicalPath $physicalPath -Port $port -ApplicationPool $appPoolName | Out-Null
  }} else {{
    Set-ItemProperty "IIS:\Sites\$siteName" -Name physicalPath -Value $physicalPath
  }}
  Set-ItemProperty "IIS:\Sites\$siteName" -Name applicationDefaults.preloadEnabled -Value $true
}}

function Ensure-Handlers-Unlocked() {{
  try {{
    $testPath = "MACHINE/WEBROOT/APPHOST"
    $null = Get-WebConfigurationProperty -PSPath $testPath -Filter "system.webServer/handlers" -Name "."
    return $true
  }} catch {{
    Write-Warning "Handlers semble verrouillé. Tentative de déverrouillage via appcmd..."
    $appcmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    & $appcmd unlock config /section:system.webServer/handlers | Out-Null
    & $appcmd unlock config /section:system.webServer/modules  | Out-Null

    try {{
      $null = Get-WebConfigurationProperty -PSPath $testPath -Filter "system.webServer/handlers" -Name "."
      Write-Host "Handlers déverrouillé."
      return $true
    }} catch {{
      Write-Warning "Impossible de déverrouiller handlers (probablement GPO). Il faudra config manuelle."
      return $false
    }}
  }}
}}

function Ensure-HttpPlatformHandler($siteName) {{
  if (-not $script:CanHandlers) {{ return }}

  $psPath = "MACHINE/WEBROOT/APPHOST"
  try {{
    $handlers = Get-WebConfigurationProperty -PSPath $psPath -Location $siteName -Filter "system.webServer/handlers" -Name "."
    $exists = $false
    foreach ($h in $handlers.Collection) {{
      if ($h.name -eq "{HANDLER_NAME}") {{ $exists = $true }}
    }}

    if (-not $exists) {{
      Add-WebConfigurationProperty -PSPath $psPath -Location $siteName -Filter "system.webServer/handlers" -Name "." -Value @{{
        name="{HANDLER_NAME}";
        path="*";
        verb="*";
        modules="{HANDLER_MODULE}";
        resourceType="Unspecified";
        requireAccess="Script"
      }} | Out-Null
    }}

    Set-WebConfigurationProperty -PSPath $psPath -Location $siteName `
      -Filter "system.webServer/handlers/add[@name='{HANDLER_NAME}']" -Name "path" -Value "*" | Out-Null
    Set-WebConfigurationProperty -PSPath $psPath -Location $siteName `
      -Filter "system.webServer/handlers/add[@name='{HANDLER_NAME}']" -Name "verb" -Value "*" | Out-Null
    Set-WebConfigurationProperty -PSPath $psPath -Location $siteName `
      -Filter "system.webServer/handlers/add[@name='{HANDLER_NAME}']" -Name "modules" -Value "{HANDLER_MODULE}" | Out-Null
    Set-WebConfigurationProperty -PSPath $psPath -Location $siteName `
      -Filter "system.webServer/handlers/add[@name='{HANDLER_NAME}']" -Name "resourceType" -Value "Unspecified" | Out-Null
    Set-WebConfigurationProperty -PSPath $psPath -Location $siteName `
      -Filter "system.webServer/handlers/add[@name='{HANDLER_NAME}']" -Name "requireAccess" -Value "Script" | Out-Null
  }} catch {{
    Write-Warning "Impossible de configurer system.webServer/handlers au niveau du site '$siteName' (section verrouillée)."
  }}
}}

function Ensure-VirtualDir($siteName, $vdirName, $targetPath) {{
  $vdirPath = "IIS:\Sites\$siteName\$vdirName"
  if (-not (Test-Path $vdirPath)) {{
    New-WebVirtualDirectory -Site $siteName -Name $vdirName -PhysicalPath $targetPath | Out-Null
  }} else {{
    Set-ItemProperty $vdirPath -Name physicalPath -Value $targetPath
  }}
}}

function Remove-Handler-In-VDir($siteName, $vdirName, $handlerName) {{
  if (-not $script:CanHandlers) {{ return }}
  $psPath = "MACHINE/WEBROOT/APPHOST"
  $location = "$siteName/$vdirName"
  try {{
    $handlers = Get-WebConfigurationProperty -PSPath $psPath -Location $location -Filter "system.webServer/handlers" -Name "."
    foreach ($h in @($handlers.Collection)) {{
      if ($h.name -eq $handlerName) {{
        Remove-WebConfigurationProperty -PSPath $psPath -Location $location -Filter "system.webServer/handlers" -Name "." -AtElement @{{name=$handlerName}} | Out-Null
      }}
    }}
  }} catch {{}}
}}

function Ensure-IIS-Logging($siteName, $logDir) {{
  $psPath = "IIS:\Sites\$siteName"
  if (-not (Test-Path $logDir)) {{
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
  }}
  Set-ItemProperty $psPath -Name logFile.enabled -Value $true
  Set-ItemProperty $psPath -Name logFile.directory -Value $logDir
  Set-ItemProperty $psPath -Name logFile.logFormat -Value "W3C"
  Set-ItemProperty $psPath -Name logFile.period -Value "MaxSize"
  Set-ItemProperty $psPath -Name logFile.truncateSize -Value 100000000
}}

$rootPath = "{str(root)}"
$logApps  = Join-Path $rootPath "logs\IIS_APPS"
$logRecipe = Join-Path $rootPath "logs\IIS_RECIPES"
$script:CanHandlers = Ensure-Handlers-Unlocked

# --- APPS
$appPoolApps = "{site_apps}_POOL"
Ensure-AppPool $appPoolApps
Ensure-Site "{site_apps}" $appPoolApps "{str(root)}" {port_apps}
Ensure-IIS-Logging "{site_apps}" $logApps
$canHandlers = Ensure-Handlers-Unlocked
Ensure-HttpPlatformHandler "{site_apps}"
Ensure-VirtualDir "{site_apps}" "{VIRTUAL_STATIC_NAME}" "{str(static_path)}"
Ensure-VirtualDir "{site_apps}" "{VIRTUAL_MEDIA_NAME}" "{str(media_path)}"
Remove-Handler-In-VDir "{site_apps}" "{VIRTUAL_STATIC_NAME}" "{HANDLER_NAME}"
Remove-Handler-In-VDir "{site_apps}" "{VIRTUAL_MEDIA_NAME}" "{HANDLER_NAME}"

# --- RECIPE
$appPoolRecipe = "{site_recipe}_POOL"
Ensure-AppPool $appPoolRecipe
Ensure-Site "{site_recipe}" $appPoolRecipe "{str(root)}" {port_recipe}
Ensure-IIS-Logging "{site_recipe}" $logRecipe
$canHandlers = Ensure-Handlers-Unlocked
Ensure-HttpPlatformHandler "{site_recipe}"
Ensure-VirtualDir "{site_recipe}" "{VIRTUAL_STATIC_NAME}" "{str(static_path)}"
Ensure-VirtualDir "{site_recipe}" "{VIRTUAL_MEDIA_NAME}" "{str(media_path)}"
Remove-Handler-In-VDir "{site_recipe}" "{VIRTUAL_STATIC_NAME}" "{HANDLER_NAME}"
Remove-Handler-In-VDir "{site_recipe}" "{VIRTUAL_MEDIA_NAME}" "{HANDLER_NAME}"

function Restart-AppPool-Safe($poolName) {{
  if (-not (Test-Path "IIS:\AppPools\$poolName")) {{ return }}
  try {{
    Restart-WebAppPool -Name $poolName -ErrorAction Stop
    Write-Host "AppPool redémarré : $poolName"
  }} catch {{
    Write-Warning "Impossible de redémarrer l'AppPool '$poolName' (droits insuffisants)."
    Write-Warning "Action manuelle: IIS Manager > Application Pools > '$poolName' > Recycle/Restart"
  }}
}}

Write-Host "----- RESTART IIS COMPONENTS -----"
Restart-AppPool-Safe "{site_apps}_POOL"
Restart-AppPool-Safe "{site_recipe}_POOL"
Write-Host "IIS prêt."
"""
    powershell(ps)

    LOG.info("\n(IIS) Terminé.")
    LOG.info(f" - {site_apps} : http://localhost:{port_apps}/")
    LOG.info(f" - {site_recipe} : http://localhost:{port_recipe}/")


def stop_iis_site(site_name: str) -> None:
    run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"Import-Module WebAdministration; "
            f"if (Test-Path IIS:\\Sites\\{site_name}) "
            f"{{ Stop-Website -Name '{site_name}' -ErrorAction SilentlyContinue }}",
        ],
        check=False,
    )


def stop_iis_for_machine(machine_num: int) -> None:
    for suffix in (SITE_SUFFIX_APPS, SITE_SUFFIX_RECIPE):
        stop_iis_site(f"{SITE_PREFIX}{machine_num:03d}{suffix}")


def _rmtree_onerror(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
    except Exception:
        pass

    try:
        func(path)
        return
    except Exception:
        pass

    try:
        subprocess.run(["cmd", "/c", "takeown", "/f", path, "/r", "/d", "y"], capture_output=True, text=True)
        subprocess.run(
            ["cmd", "/c", "icacls", path, "/grant", "Administrators:F", "/t", "/c"], capture_output=True, text=True
        )
        func(path)
        return
    except Exception:
        raise


def safe_rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path, onerror=_rmtree_onerror)
        return
    except Exception:
        pass

    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(path)], capture_output=True, text=True)

    if path.exists():
        raise PermissionError(
            f"Impossible de supprimer {path}. Un process le verrouille probablement (IIS/AV/éditeur)."
        )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument(
        "--verbose", action="store_true", help="Affiche toute la sortie des commandes (comportement proche original)."
    )
    ap.add_argument(
        "--log", type=str, default="", help="Chemin du fichier log (si vide: auto dans le dossier courant)."
    )
    return ap.parse_args(list(argv))


def main(argv: Sequence[str] = ()) -> None:
    args = parse_args(argv)
    log_path = Path(args.log) if args.log else _default_log_path()

    global LOG
    LOG = Logger(verbose=bool(args.verbose), log_file=log_path)

    LOG.section("DÉPLOIEMENT AWM (IIS)")
    LOG.info(f"Log complet: {log_path}")

    if not is_admin():
        LOG.info("⚠️ Lance ce script dans un terminal 'Exécuter en tant qu’administrateur'.")
        sys.exit(1)

    ok_py = check_python39()
    ok_mysql = check_mysql_installed()
    LOG.info(f"Prerequis: Python 3.9 OK ? {ok_py}")
    LOG.info(f"Prerequis: mysql.exe trouvé ? {ok_mysql} (indicatif)")

    ok_nssm, nssm_path = check_nssm_present()
    LOG.info(f"Prerequis: C:\\nssm\\nssm.exe trouvé ou PATH ? {ok_nssm}" + (f" ({nssm_path})" if ok_nssm else ""))

    if not ok_py:
        LOG.info("❌ Python 3.9 (py -3.9) introuvable. Installe Python 3.9 + le Python Launcher.")
        sys.exit(1)

    if not ok_nssm:
        LOG.info("❌ C:\\nssm\\nssm.exe introuvable (ou PATH).")
        sys.exit(1)

    check_prerequisites_or_exit()

    project_src = Path(ask("1) Chemin du projet AWM (dossier source) :"))
    if not project_src.exists():
        raise FileNotFoundError(project_src)

    machine_str = ask("2) Numéro machine ARP (3 chiffres, ex 105) :")
    machine_num = validate_machine_num(machine_str)
    stop_iis_for_machine(machine_num)

    target_dir = Path(ask("3) Chemin cible (où copier le projet)", DEFAULT_TARGET_DIR))
    copy_project(project_src, target_dir)

    patch_web_config_paths(target_dir, target_dir)
    configure_recipe_languages(target_dir)
    update_env_after_copy(target_dir, machine_num)

    set_execution_policy_current_user()
    create_venv_and_install(target_dir, machine_num, target_dir)

    do_services = ask("Créer les services COM via NSSM ? (y/n)", "y")
    if do_services.lower() == "y":
        create_com_services(target_dir)

    configure_iis_sites(target_dir, machine_num)

    LOG.section("FIN")
    LOG.info("✅ Terminé. (Si besoin: relancer avec --verbose pour voir toute la sortie.)")


if __name__ == "__main__":
    main(sys.argv[1:])
