"""Guard rails for the public repo.

The .gitignore is deliberately strict (it blocks anything named like the
master CV). That once silently dropped a code file from a commit, so this test
fails if any source, test, workflow or doc file would be ignored by git.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKED_DIRS = ["src", "scripts", "tests", "worker/src", "worker/test", "docs", ".github", "prompts", "templates"]
CHECKED_SUFFIXES = {".py", ".js", ".json", ".yml", ".yaml", ".md", ".toml", ".csv", ".rss", ".docx"}
HAS_GIT = shutil.which("git") is not None and (ROOT / ".git").exists()


def _project_files():
    for folder in CHECKED_DIRS:
        base = ROOT / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in CHECKED_SUFFIXES and "__pycache__" not in path.parts:
                yield path.relative_to(ROOT).as_posix()


def _ignored(paths):
    """Paths git would ignore. Bytes in and out, so Windows line endings don't interfere."""
    result = subprocess.run(["git", "check-ignore", "--no-index", "--stdin"], cwd=ROOT,
                            input="\n".join(paths).encode("utf-8"), capture_output=True)
    return [line.strip() for line in result.stdout.decode("utf-8").splitlines() if line.strip()]


@pytest.mark.skipif(not HAS_GIT, reason="needs a git checkout")
def test_no_project_file_is_silently_ignored():
    files = list(_project_files())
    assert files
    ignored = _ignored(files)
    assert ignored == [], f"These files would never reach GitHub (rename them or fix .gitignore): {ignored}"


@pytest.mark.skipif(not HAS_GIT, reason="needs a git checkout")
def test_private_material_stays_ignored():
    must_ignore = [".env", "master_cv.md", "private/notes.md", "output/cv.docx", "Peace-George-CV-Acme.docx"]
    assert sorted(_ignored(must_ignore)) == sorted(must_ignore)
