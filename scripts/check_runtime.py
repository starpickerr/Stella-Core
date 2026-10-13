"""Resolve local quality tooling on supported desktop platforms."""
import os
import shutil


def python_path(root, platform=None):
    return root / ('.venv/Scripts/python.exe' if (platform or os.name) == 'nt' else '.venv/bin/python')


def npm_path():
    return shutil.which('npm') or ('npm.cmd' if os.name == 'nt' else 'npm')
