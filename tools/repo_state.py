"""Print where the repository stands, asking GitHub rather than the local origin/* refs, which can be stale.

    .venv/Scripts/python.exe tools/repo_state.py

Reads only: ``git ls-remote`` fetches nothing and changes nothing. A commit on GitHub that was never fetched is reported as such.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*arguments: str) -> str:
    """The output of a git command, empty when it fails."""
    done = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
    return done.stdout.strip() if done.returncode == 0 else ""


def short(commit: str) -> str:
    return commit[:7]


def known_here(commit: str) -> bool:
    return bool(git("cat-file", "-t", commit))


def commits_between(older: str, newer: str, *paths: str) -> int:
    return int(git("rev-list", "--count", f"{older}..{newer}", *(("--", *paths) if paths else ())) or 0)


def main_against_github(main: str, on_github: str) -> str:
    if not on_github:
        return f"main {short(main)}; GitHub has no main"
    if not known_here(on_github):
        return f"main {short(main)}; GitHub at {short(on_github)}, not fetched"
    ahead, behind = commits_between(on_github, main), commits_between(main, on_github)
    if not (ahead or behind):
        return f"main {short(main)}, the same as GitHub"
    return f"main {short(main)}: {ahead} ahead of GitHub, {behind} behind"


def docs_site(gh_pages: str) -> str:
    if not gh_pages:
        return "docs site: no gh-pages branch on GitHub"
    if not known_here(gh_pages):
        return f"docs site: gh-pages at {short(gh_pages)}, not fetched"
    match = re.match(r"Deployed ([0-9a-f]+) ", git("log", "-1", "--format=%s", gh_pages))
    if not match:
        return f"docs site: gh-pages at {short(gh_pages)}, not deployed by mkdocs"
    deployed = match[1]
    later = commits_between(deployed, "main", "docs", "mkdocs.yml")
    return f"docs site: deployed from {deployed}, {later} commits on main since then change the docs"


def main() -> None:
    changed = len(git("status", "--porcelain").splitlines())
    print(f"on {git('branch', '--show-current') or 'a detached HEAD'} at {short(git('rev-parse', 'HEAD'))}, {changed} files changed")

    listing = git("ls-remote", "--heads", "origin")
    if not listing:
        print("GitHub not reached")
    else:
        branches = {line.split("refs/heads/")[1]: line.split()[0] for line in listing.splitlines()}
        print(main_against_github(git("rev-parse", "main"), branches.get("main", "")))
        print(docs_site(branches.get("gh-pages", "")))
        print("GitHub branches: " + ", ".join(sorted(branches)))

    tag = git("describe", "--tags", "--abbrev=0", "main")
    if tag:
        print(f"last tag {tag} ({git('log', '-1', '--format=%as', tag)}), {commits_between(tag, 'main')} commits since")

    merged = set(git("branch", "--merged", "main", "--format=%(refname:short)").splitlines())
    local = [name for name in git("branch", "--format=%(refname:short)").splitlines() if name not in ("main", "gh-pages")]
    print("local branches: " + (", ".join(f"{name} (merged)" if name in merged else name for name in local) or "none"))
    print(f"stashes: {len(git('stash', 'list').splitlines())}")
    worktrees = [line.split(" ", 1)[1] for line in git("worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]
    print("worktrees: " + ", ".join(worktrees[1:]) if worktrees[1:] else "worktrees: only this checkout")


if __name__ == "__main__":
    main()
