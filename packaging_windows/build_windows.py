"""Reproducible Windows build orchestration (Stage 14, T-05).

Pipeline (each step fails early with actionable errors):

1. ``preflight``  — environment, toolchain, version, and asset checks.
2. ``stage``      — allowlist copy of the two runtime packages + launcher
                    into ``<work>/stage`` (outside the repository).
3. ``nuitka``     — standalone compile of the thin launcher from the
                    staged tree (never from the working tree) with the
                    Nuitka-managed MinGW64 toolchain and the PySide6
                    plugin; product metadata injected from pyproject.
4. ``validate``   — distribution inspection (PE header, Python DLL,
                    Qt6 DLLs incl. ``qwindows.dll``, PySide6, policy
                    content) and a clean-environment ``--smoke`` launch
                    from a working directory containing a space, outside
                    the repository.
5. ``installer``  — Inno Setup compilation of ``installer.iss`` via
                    ISCC with version parameters from pyproject.

The work directory defaults to ``%LOCALAPPDATA%\\vscanner-build\\work``:
generated executables, caches, and installers never land in the Git tree.

CLI::

    python -m packaging_windows.build_windows [--work-dir PATH] [--iscc PATH]
        [--steps stage,nuitka,installer] [--skip-smoke] [--repo-root PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from packaging_windows import (
    APP_FILE_DESCRIPTION,
    APP_PUBLISHER,
    EXECUTABLE_NAME,
)
from packaging_windows import staging, validation, versioning

__all__ = ["BuildError", "PreflightReport", "build_distribution"]

_INSTALLER_BASENAME = "V-Scanner"


class BuildError(RuntimeError):
    """An actionable packaging failure (missing tool, bad artifact, ...)."""


@dataclass
class PreflightReport:
    """Observed environment facts recorded verbatim into the build log."""

    python_version: str
    nuitka_version: str
    pyside_version: str
    helper_versions: dict[str, str] = field(default_factory=dict)
    numeric_version: str = ""
    version: str = ""
    iscc_path: str = ""


# ---------------------------------------------------------------------------
# Paths and guards
# ---------------------------------------------------------------------------


def default_work_root() -> Path:
    """Default build workspace: ``%LOCALAPPDATA%\\vscanner-build\\work``."""
    local_app = os.environ.get("LOCALAPPDATA")
    if not local_app:
        raise BuildError(
            "LOCALAPPDATA is not set — this build pipeline runs only on "
            "Windows with a standard per-user profile"
        )
    return Path(local_app) / "vscanner-build" / "work"


def guard_work_dir(repo_root: Path, work_dir: Path) -> Path:
    """Ensure *work_dir* is writable and strictly outside *repo_root*."""
    repo_root = Path(repo_root).resolve()
    work_dir = Path(work_dir).resolve()
    if work_dir == repo_root or repo_root in work_dir.parents:
        raise BuildError(
            f"work directory must live outside the repository ({repo_root}); "
            f"got {work_dir} — the default is "
            f"{os.environ.get('LOCALAPPDATA', '%LOCALAPPDATA%')}\\vscanner-build\\work"
        )
    return work_dir


def _reset_subdir(work_dir: Path, name: str) -> Path:
    """Recreate (fresh) a build-**owned** subdirectory inside *work_dir*."""
    work_dir = Path(work_dir).resolve()
    path = work_dir / name
    if path.exists():
        if not path.is_dir():
            raise BuildError(f"work directory contains a file where {name}/ belongs: {path}")
        shutil.rmtree(path)  # build-owned workspace, guarded by guard_work_dir
    path.mkdir(parents=True)
    return path


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def preflight(repo_root: Path, work_dir: Path) -> PreflightReport:
    """Fail early on every missing build input (OSError → actionable text)."""
    repo_root = Path(repo_root)
    guard_work_dir(repo_root, _unchecked_work_dir(work_dir))

    required_repo_files = (
        "pyproject.toml",
        "vscanner/__init__.py",
        "vscanner/core/paths.py",
        "ui_desktop/__init__.py",
        "ui_desktop/app.py",
        f"packaging_windows/{staging.LAUNCHER_NAME}",
        "packaging_windows/installer.iss",
        "packaging_windows/assets/vscanner.ico",
    )
    for required in required_repo_files:
        checked = repo_root / required
        if not checked.is_file():
            raise BuildError(
                f"required build input is missing: {checked}\n"
                "run from the repository root (or pass --repo-root)"
            )

    if sys.version_info < (3, 10):
        raise BuildError(
            f"Python {sys.version_info[:2]} is too old for the packaging "
            "tooling (the repository floor is 3.10)"
        )

    version = versioning.parse_pyproject_version(repo_root / "pyproject.toml")
    quad = versioning.derive_version_quad(version)

    try:
        nuitka_version = importlib.metadata.version("nuitka")
    except importlib.metadata.PackageNotFoundError as exc:
        raise BuildError(
            "Nuitka is not installed in this Python environment.\n"
            "  pip install --user nuitka ordered-set zstandard\n"
            f"(searched: {sys.executable})"
        ) from exc

    try:
        pyside_version = importlib.metadata.version("PySide6")
    except importlib.metadata.PackageNotFoundError as exc:
        raise BuildError(
            "PySide6 is not installed; the desktop extra is required to "
            "build the desktop distribution: pip install -e '.[desktop]'"
        ) from exc

    helpers: dict[str, str] = {}
    for pkg in ("ordered-set", "zstandard"):
        try:
            helpers[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            helpers[pkg] = "not installed (optional)"

    # Validate the committed icon structurally and through Qt decode.
    validation.validate_icon_file(repo_root / "packaging_windows/assets/vscanner.ico")

    report = PreflightReport(
        python_version=".".join(map(str, sys.version_info[:3])),
        nuitka_version=nuitka_version,
        pyside_version=pyside_version,
        helper_versions=helpers,
        numeric_version=quad,
        version=version,
    )
    return report


def _unchecked_work_dir(work_dir: "Path | None") -> Path:
    if work_dir is None:
        return default_work_root()
    return Path(work_dir)


# ---------------------------------------------------------------------------
# Nuitka standalone compile
# ---------------------------------------------------------------------------


def prepare_stage(repo_root: Path, work_dir: Path) -> Path:
    """Fresh stage directory under the guarded work root."""
    guard_work_dir(repo_root, work_dir)
    stage_root = _reset_subdir(work_dir, "stage")
    report = staging.stage_release_tree(repo_root, stage_root)
    validation.validate_staged_tree(stage_root)
    print(f"[stage] copied {report.copied_files} files "
          f"({{pkg: files}} {report.per_package}) → {stage_root}")
    return stage_root


def run_nuitka(
    stage_root: Path,
    work_dir: Path,
    *,
    version: str,
    numeric_version: str,
    icon_path: Path,
    log_dir: Path,
) -> Path:
    """Compile the staged launcher standalone; return the dist directory.

    cwd is the staged tree, never the repository: the compiled closure is
    provably the staged one. The Nuitka-managed MinGW64 toolchain is
    fetched into its user cache on first use (--assume-yes-for-downloads).
    """
    output_dir = work_dir / "nuitka"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "nuitka.log"

    command = [
        sys.executable, "-m", "nuitka",
        "--mode=standalone",
        "--assume-yes-for-downloads",
        "--mingw64",
        "--enable-plugins=pyside6",
        "--include-package=vscanner",
        "--include-package=ui_desktop",
        "--nofollow-import-to=ui_terminal",
        "--nofollow-import-to=tests",
        "--nofollow-import-to=cli",
        "--nofollow-import-to=android",
        "--windows-console-mode=disable",
        f"--windows-icon-from-ico={icon_path}",
        f"--company-name={APP_PUBLISHER}",
        "--product-name=V-Scanner",
        f"--product-version={numeric_version}",
        f"--file-version={numeric_version}",
        f"--file-description={APP_FILE_DESCRIPTION}",
        f"--output-dir={output_dir}",
        f"--output-folder-name={_INSTALLER_BASENAME}",
        f"--output-filename={EXECUTABLE_NAME}",
        str(stage_root / staging.LAUNCHER_NAME),
    ]

    print("[nuitka] compiling standalone distribution "
          f"(version {version}, numeric {numeric_version}) …")
    with log_file.open("w", encoding="utf-8", errors="replace") as sink:
        proc = subprocess.run(
            command,
            cwd=str(stage_root),
            stdout=sink,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    if proc.returncode != 0:
        raise BuildError(
            f"Nuitka failed with exit code {proc.returncode}; full log at "
            f"{log_file} (tail: {_tail(log_file)})"
        )

    dist_dir = output_dir / f"{_INSTALLER_BASENAME}.dist"
    if not dist_dir.is_dir():
        found = sorted(path.name for path in output_dir.glob("*.dist"))
        raise BuildError(
            f"Nuitka did not produce {dist_dir}; found: {found} (log: {log_file})"
        )
    print(f"[nuitka] produced {dist_dir}")
    return dist_dir


def _tail(path: Path, lines: int = 8) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"(log unreadable: {exc})"
    return "\n".join(content[-lines:])


# ---------------------------------------------------------------------------
# Inno Setup compilation
# ---------------------------------------------------------------------------


def find_iscc(repo_root: Path, explicit: "Path | str | None" = None) -> Path:
    """Locate ISCC.exe (explicit arg → env → sanctioned tools → install dirs).

    Download source (official, documented): https://jrsoftware.org/isdl.php —
    the portable ``innosetup-6.x.x.zip`` extracted under
    ``%LOCALAPPDATA%\\vscanner-build\\inno\\`` is the build-scope default.
    """
    local_app = os.environ.get("LOCALAPPDATA", "")
    if explicit is not None:
        candidate = Path(str(explicit)).resolve()
        if candidate.is_file() and candidate.name.lower() == "iscc.exe":
            return candidate
        if candidate.is_dir():
            found = candidate / "ISCC.exe"
            if found.is_file():
                return found
        raise BuildError(
            f"explicit ISCC path is not a file or directory with ISCC.exe: {candidate}"
        )
    env_iscc = os.environ.get("VSCANNER_INNO_SETUP")
    if env_iscc:
        return find_iscc(repo_root, env_iscc)
    if local_app:
        tools_dir = Path(local_app) / "vscanner-build" / "inno"
        if tools_dir.is_dir():
            found_path = next(iter(sorted(tools_dir.rglob("ISCC.exe"))), None)
            if found_path is not None:
                return found_path
    standard_dirs = (
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Inno Setup 6" / "ISCC.exe",
    )
    for candidate in standard_dirs:
        if candidate.is_file():
            return candidate
    raise BuildError(
        "ISCC.exe (Inno Setup 6 compiler) was not found.\n"
        "  1. Download the official portable zip from https://jrsoftware.org/isdl.php\n"
        f"  2. Extract it under {local_app}\\vscanner-build\\inno\\  (no admin needed), or\n"
        "  3. Pass --iscc PATH (or set VSCANNER_INNO_SETUP) to an existing ISCC.exe."
    )


def compile_installer(
    dist_dir: Path,
    work_dir: Path,
    *,
    version: str,
    numeric_version: str,
    iscc_path: Path,
    repo_root: Path,
    log_dir: Path,
) -> Path:
    """Compile ``installer.iss`` against the validated dist; return the exe."""
    iss_path = repo_root / "packaging_windows" / "installer.iss"
    if not iss_path.is_file():
        raise BuildError(f"installer script is missing: {iss_path}")
    if not dist_dir.is_dir():
        raise BuildError(f"distribution directory is missing: {dist_dir}")

    output_dir = work_dir / "installer"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "iscc.log"

    command = [
        str(iscc_path),
        f"/DVSCANNER_VERSION={version}",
        f"/DVSCANNER_RESOURCE_VERSION={numeric_version}",
        f"/DVSCANNER_STAGE_DIR={dist_dir}",
        f"/DVSCANNER_OUT_DIR={output_dir}",
        f"/DVSCANNER_REPO_ROOT={repo_root}",
        str(iss_path),
    ]
    print(f"[installer] compiling with {iscc_path} …")
    with log_file.open("w", encoding="utf-8", errors="replace") as sink:
        proc = subprocess.run(
            command,
            stdout=sink,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    if proc.returncode != 0:
        raise BuildError(
            f"Inno Setup compiler failed with exit code {proc.returncode}; "
            f"full log at {log_file} (tail: {_tail(log_file)})"
        )
    installer_path = output_dir / f"{_INSTALLER_BASENAME}-{version}-Setup.exe"
    if not installer_path.is_file():
        raise BuildError(
            f"expected installer is missing after compilation: {installer_path} "
            f"(log: {log_file})"
        )
    print(f"[installer] produced {installer_path}")
    return installer_path


def smoke_validate(dist_dir: Path, work_dir: Path) -> str:
    """Validate distribution, then launch it from an outside path with a space."""
    report = validation.validate_distribution(dist_dir)
    print(f"[validate] dist OK: {report.files} files "
          f"({report.total_bytes / 1024.0 / 1024.0:.1f} MiB), "
          f"dll patterns found: {sorted(set(r.name for r in report.dlls_found.values()))}")

    local_app = os.environ.get("LOCALAPPDATA", str(work_dir))
    run_dir = Path(local_app) / "vscanner-build" / "run dir with spaces"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[smoke] launching {report.executable} from {run_dir} …")
    stdout = validation.smoke_launch(report.executable, run_dir)
    print(f"[smoke] OK ({stdout.strip()!r})")
    return stdout


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Pipeline and CLI
# ---------------------------------------------------------------------------


@dataclass
class StepDecision:
    steps: "tuple[str, ...]"


def build_distribution(
    repo_root: "Path | None" = None,
    work_dir: "Path | None" = None,
    *,
    iscc: "Path | str | None" = None,
    steps: "tuple[str, ...]" = ("stage", "nuitka", "installer"),
    skip_smoke: bool = False,
) -> "dict[str, object]":
    """Run the selected pipeline steps; return compiled-artifact facts."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    repo_root = Path(repo_root).resolve()
    if work_dir is None:
        work_dir = default_work_root()
    work_dir = guard_work_dir(repo_root, Path(work_dir))
    log_dir = work_dir / "logs"

    report = preflight(repo_root, work_dir)
    print(f"[preflight] package={repo_root.name} "
          f"python={report.python_version} nuitka={report.nuitka_version} "
          f"pyside6={report.pyside_version} "
          f"version={report.version} numeric={report.numeric_version} "
          f"helpers={report.helper_versions}")

    facts: dict[str, object] = {
        "repo_root": str(repo_root),
        "work_dir": str(work_dir),
        "python_version": report.python_version,
        "nuitka_version": report.nuitka_version,
        "pyside_version": report.pyside_version,
        "version": report.version,
        "numeric_version": report.numeric_version,
    }
    if "stage" in steps:
        facts["stage_dir"] = str(prepare_stage(repo_root, work_dir))
    if "nuitka" in steps:
        stage_root = Path(str(facts.get("stage_dir") or (work_dir / "stage")))
        dist_dir = run_nuitka(
            stage_root, work_dir,
            version=report.version,
            numeric_version=report.numeric_version,
            icon_path=repo_root / "packaging_windows" / "assets" / "vscanner.ico",
            log_dir=log_dir,
        )
        facts["dist_dir"] = str(dist_dir)
        if not skip_smoke:
            facts["smoke_stdout"] = smoke_validate(dist_dir, work_dir)
    if "installer" in steps:
        iscc_path = find_iscc(repo_root, iscc)
        report.iscc_path = str(iscc_path)
        facts["iscc_path"] = str(iscc_path)
        dist_dir = Path(str(facts.get("dist_dir") or (work_dir / "nuitka" / f"{_INSTALLER_BASENAME}.dist")))
        installer_path = compile_installer(
            dist_dir, work_dir,
            version=report.version,
            numeric_version=report.numeric_version,
            iscc_path=iscc_path,
            repo_root=repo_root,
            log_dir=log_dir,
        )
        facts["installer_path"] = str(installer_path)
        facts["installer_sha256"] = sha256_of(installer_path)
        facts["installer_bytes"] = installer_path.stat().st_size
    return facts


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        prog="packaging_windows.build_windows",
        description="Stage 14: reproducible V-Scanner Windows build (T-05)")
    parser.add_argument("--repo-root", type=Path, default=None,
                        help="repository root (default: package parent)")
    parser.add_argument("--work-dir", type=Path, default=None,
                        help="build workspace (default: %%LOCALAPPDATA%%\\vscanner-build\\work)")
    parser.add_argument("--iscc", type=str, default=None,
                        help="path to ISCC.exe (default: discovery)")
    parser.add_argument("--steps", type=str, default="stage,nuitka,installer",
                        help="comma list of: stage,nuitka,installer")
    parser.add_argument("--skip-smoke", action="store_true",
                        help="skip the packaged --smoke launch validation")
    args = parser.parse_args(argv)

    try:
        steps = tuple(step.strip() for step in args.steps.split(",") if step.strip())
        known = {"stage", "nuitka", "installer"}
        unknown = set(steps) - known
        if unknown:
            raise BuildError(f"unknown steps {sorted(unknown)}; choose from {sorted(known)}")
        facts = build_distribution(
            repo_root=args.repo_root,
            work_dir=args.work_dir,
            iscc=args.iscc,
            steps=steps,
            skip_smoke=args.skip_smoke,
        )
    except BuildError as error:
        print(f"BUILD FAILED: {error}", file=sys.stderr)
        return 1
    print("[done] artifact facts:")
    for key, value in facts.items():
        print(f"  {key} = {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
