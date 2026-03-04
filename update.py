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
    return str(path).replace("/", "\\").lstrip(".\\")


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
    r"web\db",
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
            shutil.copy2(src_file, dst_file)


# ---------- Post update steps ----------


def venv_python(awm_root: Path) -> Path:
    py = awm_root / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        raise RuntimeError(f"Python venv introuvable: {py} (la venv doit déjà exister dans le projet existant).")
    return py


def update_venv_if_possible(awm_root: Path, *, internet_ok: bool) -> None:
    if not internet_ok:
        print("⚠️ Pas d'accès internet: la venv ne sera pas mise à jour (pip install ignoré).")
        return

    req = awm_root / "requirement.txt"
    if not req.exists():
        req2 = awm_root / "requirements.txt"
        if req2.exists():
            req = req2
        else:
            print("⚠️ requirement.txt / requirements.txt introuvable: mise à jour pip ignorée.")
            return

    py = venv_python(awm_root)
    print(f"⬆️  Mise à jour venv via: {req.name}")
    run([str(py), "-m", "pip", "install", "-r", str(req)], cwd=awm_root, check=True)


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
    print(f"\nInternet (pypi.org:443) : {'OK' if internet_ok else 'NON'}")

    if not internet_ok:
        cont = ask_yes_no(
            "Pas de connexion internet. Les librairies de la venv ne pourront pas être mises à jour. Continuer ?",
            default_yes=False,
        )
        if not cont:
            print("⛔ Annulé.")
            return 1

    print("\n----- SYNCHRO FICHIERS -----")
    print("⚠️  Exclusions (non modifiés) :")
    for ex in EXCLUDED_PREFIXES:
        print(f" - {ex}")
    print("\n📁 Copie / mise à jour en cours...")
    sync_tree(src, dst)
    print("✅ Fichiers mis à jour (hors exclusions).")

    print("\n----- POST-UPDATE -----")
    update_venv_if_possible(dst, internet_ok=internet_ok)

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
