"""Print/resolve the shared Conda Stella interpreter for development tooling."""
import os
import shutil
import sys
from pathlib import Path


def _standard_roots(home, platform):
    roots = [home / name for name in ('anaconda3', 'miniconda3', 'miniforge3', 'mambaforge', '.conda')]
    if platform == 'nt':
        roots.extend(Path(os.environ.get('LOCALAPPDATA', str(home / 'AppData/Local'))) / name
                     for name in ('anaconda3', 'miniconda3', 'miniforge3'))
        roots.extend(Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / name
                     for name in ('anaconda3', 'miniconda3', 'miniforge3'))
    else:
        roots.extend(Path('/opt') / name for name in ('anaconda3', 'miniconda3', 'miniforge3'))
        roots.append(Path('/opt/homebrew/Caskroom/miniconda/base'))
    conda = os.environ.get('CONDA_EXE')
    if conda:
        roots.insert(0, Path(conda).parent.parent)
    return roots


def python_path(root=None, platform=None):
    """Honor STELLA_PYTHON; otherwise find named Conda Stella, never a venv fallback."""
    platform = platform or os.name
    root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    override = os.environ.get('STELLA_PYTHON')
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            located = shutil.which(override) if candidate.parent == Path('.') else None
            candidate = Path(located) if located else root / candidate
        if candidate.is_file() and (platform == 'nt' or os.access(candidate, os.X_OK)):
            return candidate.absolute()
        raise FileNotFoundError(f'STELLA_PYTHON is not an executable: {override}')

    home = Path.home()
    candidates = [Path(os.environ['CONDA_PREFIX'])] if os.environ.get('CONDA_PREFIX') else []
    candidates.append(Path(sys.prefix))
    registry = home / '.conda/environments.txt'
    if registry.is_file():
        candidates.extend(Path(line.strip()) for line in registry.read_text(encoding='utf-8').splitlines()
                          if line.strip())
    for directory in os.environ.get('CONDA_ENVS_PATH', '').split(os.pathsep):
        if directory:
            candidates.extend(Path(directory) / name for name in ('Stella', 'stella'))
    for base in _standard_roots(home, platform):
        candidates.extend(base / 'envs' / name for name in ('Stella', 'stella'))
    for prefix in candidates:
        executable = prefix / ('python.exe' if platform == 'nt' else 'bin/python')
        if (prefix.name.casefold() == 'stella' and (prefix / 'conda-meta').is_dir()
                and executable.is_file() and (platform == 'nt' or os.access(executable, os.X_OK))):
            return executable.absolute()
    raise FileNotFoundError(
        "Conda environment 'Stella' was not found. Create it with "
        "'conda create -n Stella python=3.12', or set STELLA_PYTHON to its Python executable."
    )


def npm_path():
    return shutil.which('npm') or ('npm.cmd' if os.name == 'nt' else 'npm')


if __name__ == '__main__':
    try:
        print(python_path())
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
