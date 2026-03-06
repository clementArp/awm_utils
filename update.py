#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update.py - Met à jour une installation AWM existante à partir d'un dossier AWM plus récent.

Règles :
- Copie/écrase tout depuis "AWM récent" -> "AWM existant"
- SAUF (ne jamais modifier) :
    - venv/
    - .env
    - web/db/
    - web/src/media/

Puis :
- (si internet) pip install -r requirement.txt dans la venv existante
- makemigrations
- migrate --database=diagnostic_db
- collectstatic --noinput

Usage:
  py update.py
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
import stat

WHEELHOUSE_DIR = "wheelhouse"


# ---------- Utils ----------


@dataclass
class CmdResult:
    cmd: Sequence[str]
    returncode: int
    stdout: str
    stderr: str


def run(cmd: Sequence[str], *, cwd: Optional[Path] = None, check: bool = True) -> CmdResult:
    p = subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    if check and p.returncode != 0:
        raise RuntimeError(
            f"Commande échouée ({p.returncode}): {' '.join(cmd)}\n\nSTDOUT:\n{p.stdout}\n\nSTDERR:\n{p.stderr}"
        )
    return CmdResult(cmd=cmd, returncode=p.returncode, stdout=p.stdout or "", stderr=p.stderr or "")


def ask_path(prompt: str) -> Path:
    while True:
        s = input(prompt).strip().strip('"').strip("'")
        p = Path(s)
        if p.exists() and p.is_dir():
            return p
        print(f"❌ Dossier introuvable: {p}")


def ask_yes_no(prompt: str, default_yes: bool = True) -> bool:
    suffix = "[y]" if default_yes else "[n]"
    while True:
        s = input(f"{prompt} (y/n) {suffix} ").strip().lower()
        if not s:
            return default_yes
        if s in {"y", "yes", "o", "oui"}:
            return True
        if s in {"n", "no", "non"}:
            return False
        print("Réponse attendue: y ou n.")


def has_internet(host: str = "pypi.org", port: int = 443, timeout_s: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def rel_norm(path: Path) -> str:
    return str(path).replace("/", "\\")


def is_excluded(rel: str, excluded_prefixes: Tuple[str, ...]) -> bool:
    rel_ci = rel.lower().strip("\\")
    for ex in excluded_prefixes:
        ex_ci = ex.lower().strip("\\")
        if rel_ci == ex_ci or rel_ci.startswith(ex_ci + "\\"):
            return True
    return False


# ---------- Sync logic ----------

EXCLUDED_PREFIXES: Tuple[str, ...] = (
    r"venv",
    r"logs",
    r".env",
    r"com\main\logger",
    r"web\db\recipes",
    r"web\src\media",
)


def sync_tree(src_root: Path, dst_root: Path, excluded_prefixes: Tuple[str, ...] = EXCLUDED_PREFIXES) -> None:
    """
    Copie src_root -> dst_root en écrasant ce qui existe,
    sans modifier les chemins exclus.
    Ne supprime pas les fichiers présents dans dst_root mais absents du src_root.
    """
    src_root = src_root.resolve()
    dst_root = dst_root.resolve()

    if src_root == dst_root:
        raise RuntimeError("Le dossier source (récent) et le dossier cible (existant) ne peuvent pas être identiques.")

    for cur_dir, dirnames, filenames in os.walk(src_root):
        cur_dir_p = Path(cur_dir)
        rel_dir = rel_norm(cur_dir_p.relative_to(src_root))

        # Si le dossier courant est exclu -> ne pas descendre
        if rel_dir and is_excluded(rel_dir, excluded_prefixes):
            dirnames[:] = []
            continue

        # Filtrer les sous-dossiers exclus pour éviter de descendre dedans
        kept_dirnames: List[str] = []
        for d in dirnames:
            rel_child = rel_norm((cur_dir_p / d).relative_to(src_root))
            if is_excluded(rel_child, excluded_prefixes):
                continue
            kept_dirnames.append(d)
        dirnames[:] = kept_dirnames

        # Créer le dossier cible correspondant
        dst_dir = dst_root / (rel_dir if rel_dir else "")
        dst_dir.mkdir(parents=True, exist_ok=True)

        # Copier les fichiers
        for f in filenames:
            rel_file = rel_norm((cur_dir_p / f).relative_to(src_root))
            if is_excluded(rel_file, excluded_prefixes):
                continue

            src_file = cur_dir_p / f
            dst_file = dst_root / rel_file
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            try:
                if dst_file.exists():
                    try:
                        os.chmod(dst_file, stat.S_IWRITE)
                    except OSError:
                        pass

                    try:
                        dst_file.unlink()
                    except PermissionError:
                        time.sleep(0.2)
                        try:
                            os.chmod(dst_file, stat.S_IWRITE)
                        except OSError:
                            pass
                        dst_file.unlink()

                shutil.copy2(src_file, dst_file)

            except PermissionError as e:
                print(f"⚠️ Impossible de remplacer: {dst_file}")
                raise PermissionError(
                    f"Accès refusé lors du remplacement de '{dst_file}'. "
                    f"Le fichier est probablement verrouillé, en lecture seule, ou protégé."
                ) from e


# ---------- Post update steps ----------


def venv_python(awm_root: Path) -> Path:
    py = awm_root / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        raise RuntimeError(f"Python venv introuvable: {py} (la venv doit déjà exister dans le projet existant).")
    return py


def choose_venv_update_mode(src_root: Path, internet_ok: bool) -> str:
    """
    Retourne:
      - 'online'
      - 'offline-wheelhouse'
      - 'skip'
    Peut lever RuntimeError si l'utilisateur annule.
    """
    wheelhouse = src_root / WHEELHOUSE_DIR
    wheelhouse_ok = wheelhouse.exists() and wheelhouse.is_dir()

    print("\n----- VENV / CONNECTIVITÉ -----")
    print(f"Internet (pypi.org:443) : {'OK' if internet_ok else 'NON'}")
    print(f"Wheelhouse source       : {'OK' if wheelhouse_ok else 'NON'} ({wheelhouse})")

    if internet_ok:
        print("✅ La mise à jour de la venv se fera via Internet.")
        if not ask_yes_no("Continuer avec cette configuration ?", default_yes=True):
            raise RuntimeError("Opération annulée avant la copie.")
        return "online"

    print("⚠️ Aucun accès Internet détecté.")

    if wheelhouse_ok:
        use_wheelhouse = ask_yes_no(
            f"Utiliser '{WHEELHOUSE_DIR}' du dossier source pour mettre à jour la venv hors ligne ?",
            default_yes=True,
        )
        if use_wheelhouse:
            if not ask_yes_no("Confirmer et continuer ?", default_yes=True):
                raise RuntimeError("Opération annulée avant la copie.")
            return "offline-wheelhouse"

    skip_update = ask_yes_no(
        "Continuer sans mettre à jour la venv ?",
        default_yes=False,
    )
    if skip_update:
        if not ask_yes_no("Confirmer et continuer sans mise à jour de la venv ?", default_yes=True):
            raise RuntimeError("Opération annulée avant la copie.")
        return "skip"

    raise RuntimeError("Opération annulée avant la copie.")


def update_venv_if_possible(awm_root: Path, *, mode: str) -> bool:
    """
    mode:
      - 'online'
      - 'offline-wheelhouse'
      - 'skip'
    Retourne True si update faite, False si ignorée.
    """
    req = awm_root / "requirement.txt"
    if not req.exists():
        req2 = awm_root / "requirements.txt"
        if req2.exists():
            req = req2
        else:
            print("⚠️ requirement.txt / requirements.txt introuvable: mise à jour pip ignorée.")
            return False

    py = venv_python(awm_root)

    if mode == "online":
        print(f"⬆️  Mise à jour venv via Internet avec: {req.name}")
        run([str(py), "-m", "pip", "install", "-r", str(req)], cwd=awm_root, check=True)
        return True

    if mode == "offline-wheelhouse":
        wheelhouse = awm_root / WHEELHOUSE_DIR
        if not wheelhouse.exists() or not wheelhouse.is_dir():
            raise RuntimeError(f"Dossier '{WHEELHOUSE_DIR}' introuvable après copie: {wheelhouse}")

        print(f"⬆️  Mise à jour venv hors ligne via: {wheelhouse}")
        run(
            [
                str(py),
                "-m",
                "pip",
                "install",
                "--no-index",
                f"--find-links={wheelhouse}",
                "-r",
                str(req),
            ],
            cwd=awm_root,
            check=True,
        )
        return True

    if mode == "skip":
        print("⚠️ Mise à jour de la venv ignorée.")
        return False

    raise RuntimeError(f"Mode de mise à jour inconnu: {mode}")


def django_manage(awm_root: Path, args: Sequence[str]) -> None:
    py = venv_python(awm_root)
    manage = awm_root / "web" / "src" / "manage.py"
    if not manage.exists():
        raise RuntimeError(f"manage.py introuvable: {manage}")
    run([str(py), str(manage), *args], cwd=awm_root, check=True)


# ---------- Main ----------


def main() -> int:
    print("====================================")
    print("   AWM - Update d'un projet existant")
    print("====================================\n")

    src = ask_path("Chemin du dossier AWM récent (source) : ")
    dst = ask_path("Chemin du dossier AWM existant (cible) : ")

    internet_ok = has_internet()

    try:
        venv_update_mode = choose_venv_update_mode(src, internet_ok)
    except RuntimeError as e:
        print(f"⛔ {e}")
        return 1

    print("\n----- SYNCHRO FICHIERS -----")
    print("⚠️  Exclusions (non modifiés) :")
    for ex in EXCLUDED_PREFIXES:
        print(f" - {ex}")

    if not ask_yes_no("Lancer la copie / mise à jour des fichiers ?", default_yes=True):
        print("⛔ Opération annulée avant la copie.")
        return 1

    print("\n📁 Copie / mise à jour en cours...")
    sync_tree(src, dst)
    print("✅ Fichiers mis à jour (hors exclusions).")

    print("\n----- POST-UPDATE -----")
    update_venv_if_possible(dst, mode=venv_update_mode)

    print("🧩 Django: makemigrations")
    django_manage(dst, ["makemigrations"])

    print("🧩 Django: migrate (diagnostic_db)")
    django_manage(dst, ["migrate", "--database=diagnostic_db"])

    print("🧩 Django: collectstatic")
    django_manage(dst, ["collectstatic", "--noinput"])

    print("\n✅ Update terminé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
