from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ARTIFACT_NAME = "nexmagi-sidecar"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _artifact_name() -> str:
    if sys.platform.startswith("win"):
        return f"{ARTIFACT_NAME}.exe"
    return ARTIFACT_NAME


def main() -> int:
    repo_root = _repo_root()
    entry_script = repo_root / "desktop" / "scripts" / "sidecar_entry.py"
    resources_dir = repo_root / "desktop" / "src-tauri" / "resources" / "bin"
    build_root = repo_root / ".build" / "pyinstaller" / ARTIFACT_NAME
    config_dir = repo_root / ".build" / "pyinstaller" / "config"
    dist_dir = build_root / "dist"
    work_dir = build_root / "work"
    spec_dir = build_root / "spec"
    artifact_path = resources_dir / _artifact_name()
    pyinstaller_env = os.environ.copy()
    pyinstaller_env["PYINSTALLER_CONFIG_DIR"] = str(config_dir)

    pyinstaller = [sys.executable, "-m", "PyInstaller"]
    try:
        subprocess.run(
            pyinstaller + ["--version"],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
            env=pyinstaller_env,
        )
    except (OSError, subprocess.CalledProcessError):
        print(
            "PyInstaller が見つかりません。"
            " `python3 -m pip install -r local_worker/requirements-build.txt` を実行してください。",
            file=sys.stderr,
        )
        return 1

    resources_dir.mkdir(parents=True, exist_ok=True)
    build_root.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    if artifact_path.exists():
        artifact_path.unlink()

    command = [
        *pyinstaller,
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        ARTIFACT_NAME,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(repo_root),
        "--paths",
        str(repo_root / "sidecar"),
        str(entry_script),
    ]
    subprocess.run(command, cwd=str(repo_root), check=True, env=pyinstaller_env)

    built_artifact = dist_dir / _artifact_name()
    if not built_artifact.exists():
        print(f"artifact not found: {built_artifact}", file=sys.stderr)
        return 1

    shutil.copy2(built_artifact, artifact_path)
    print(f"built {artifact_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
