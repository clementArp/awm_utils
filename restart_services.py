#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Restart AWM COM services (10 services total).

Stops then starts:
  - AWM_COM_APPS_1..5
  - AWM_COM_RECIPE_1..5

Usage (Admin):
  py restart_services.py
  py restart_services.py --nssm "C:\nssm\nssm.exe"
  py restart_services.py --count 5

Notes:
- Requires administrative privileges to stop/start services.
- Uses NSSM if available, otherwise falls back to sc.exe.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence


@dataclass
class CmdResult:
    cmd: Sequence[str]
    returncode: int
    stdout: str
    stderr: str


def run(cmd: Sequence[str], *, check: bool = False) -> CmdResult:
    p = subprocess.run(
        list(cmd),
        text=True,
        capture_output=True,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"Commande échouée ({p.returncode}): {' '.join(cmd)}\n{p.stderr}")
    return CmdResult(cmd=cmd, returncode=p.returncode, stdout=p.stdout or "", stderr=p.stderr or "")


def find_nssm(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        p = Path(explicit)
        return str(p) if p.exists() else None

    for c in [
        Path(r"C:\nssm\nssm.exe"),
        Path(r"C:\tools\nssm\nssm.exe"),
        Path(r"C:\nssm.exe"),
        Path(r"C:\tools\nssm.exe"),
    ]:
        if c.exists():
            return str(c)

    return shutil.which("nssm")


def services_list(count: int) -> List[str]:
    return [f"AWM_COM_APPS_{i}" for i in range(1, count + 1)] + [f"AWM_COM_RECIPE_{i}" for i in range(1, count + 1)]


def nssm_status(nssm: str, service: str) -> str:
    r = run([nssm, "status", service], check=False)

    raw = (r.stdout + "\n" + r.stderr).strip()

    # Normalisation robuste :
    # - enlève NUL éventuels
    # - enlève tous les espaces/retours
    normalized = raw.replace("\x00", "")
    normalized = "".join(normalized.split())  # supprime TOUS les espaces/newlines/tabs

    return normalized


def stop_service(service: str, *, nssm: Optional[str]) -> None:
    if nssm:
        run([nssm, "stop", service], check=False)
    else:
        run(["sc", "stop", service], check=False)


def start_service(service: str, *, nssm: Optional[str]) -> None:
    if nssm:
        run([nssm, "start", service], check=False)
    else:
        run(["sc", "start", service], check=False)


def wait_stopped(service: str, *, nssm: Optional[str], timeout_s: float = 20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st = nssm_status(nssm, service).upper()
        if nssm:
            if "STOPPED" in st or "SERVICE_STOPPED" in st:
                return True
        else:
            r = run(["sc", "query", service], check=False)
            txt = (r.stdout + "\n" + r.stderr).upper()
            if "STATE" in txt and "STOPPED" in txt:
                return True
        time.sleep(0.5)
    return False


def wait_running(service: str, *, nssm: Optional[str], timeout_s: float = 20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if nssm:
            st = nssm_status(nssm, service).upper()
            if "RUNNING" in st or "SERVICE_RUNNING" in st:
                return True
        else:
            r = run(["sc", "query", service], check=False)
            txt = (r.stdout + "\n" + r.stderr).upper()
            if "STATE" in txt and "RUNNING" in txt:
                return True
        time.sleep(0.5)
    return False


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Stop then start AWM COM services (APPS + RECIPE).")
    ap.add_argument("--nssm", help=r"Path to nssm.exe (default: auto-detect).", default=None)
    ap.add_argument("--count", help="Number of COM instances (default: 5).", type=int, default=5)
    ap.add_argument("--no-wait", help="Do not wait for stop/start states.", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    nssm = find_nssm(args.nssm)
    if nssm:
        print(f"✅ NSSM détecté: {nssm}")
    else:
        print("ℹ️ NSSM non détecté, utilisation de sc.exe")

    svcs = services_list(args.count)

    print("\n----- STOP -----")
    for s in svcs:
        print(f"⏹️  {s}")
        stop_service(s, nssm=nssm)
        if not args.no_wait:
            print("   ✅ stopped" if wait_stopped(s, nssm=nssm) else "   ⚠️ timeout")
            if not wait_stopped(s, nssm=nssm):
                print(f"nssm_status: {nssm_status(nssm, s)}")

    print("\n----- START -----")
    for s in svcs:
        print(f"▶️  {s}")
        start_service(s, nssm=nssm)
        if not args.no_wait:
            print("   ✅ running" if wait_running(s, nssm=nssm) else "   ⚠️ timeout")
            if not wait_running(s, nssm=nssm):
                print(f"nssm_status: {nssm_status(nssm, s)}")

    print("\n✅ Terminé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
