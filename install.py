#!/usr/bin/env python3
"""Install the rust-elegant skill for Claude Code and/or Codex.

Works on Linux, macOS and Windows with Python 3.8+ and the standard library only.

From a clone of the repository:
    python3 install.py                  # install for every detected tool
    python3 install.py --target codex   # only Codex
    python3 install.py --project .      # install into a project instead of the user directory
    python3 install.py --link           # symlink to the clone, so `git pull` updates the skill
    python3 install.py --uninstall

Without cloning (the script downloads the repository archive itself):
    curl -fsSL https://raw.githubusercontent.com/fuqiuluo/rust-elegant/main/install.py | python3 -
    irm https://raw.githubusercontent.com/fuqiuluo/rust-elegant/main/install.py | python -
"""

import argparse
import io
import os
import shutil
import ssl
import stat
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Callable, List, NamedTuple, NoReturn, Optional

if sys.version_info < (3, 8):
    sys.exit("rust-elegant installer needs Python 3.8 or newer.")

SKILL_NAME = "rust-elegant"
REPO = "fuqiuluo/rust-elegant"
DEFAULT_REF = "main"
# Only these are installed; README.md, install.py etc. stay in the repository.
SKILL_FILE = "SKILL.md"
SKILL_DIRS = ("references",)


def claude_home() -> Path:
    return Path.home() / ".claude"


def codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    return Path(env).expanduser() if env else Path.home() / ".codex"


class Tool(NamedTuple):
    key: str
    label: str
    command: str
    home: Callable[[], Path]
    user_skills: Callable[[], Path]
    project_skills: str


TOOLS = (
    Tool("claude", "Claude Code", "claude", claude_home,
         lambda: claude_home() / "skills", ".claude/skills"),
    # Codex also reads ~/.agents/skills; $CODEX_HOME/skills is where its own
    # skill installer puts user skills, and it is not shared with other agents.
    Tool("codex", "Codex", "codex", codex_home,
         lambda: codex_home() / "skills", ".agents/skills"),
)


def info(msg: str) -> None:
    print(msg)


def warn(msg: str) -> None:
    print("warning: " + msg, file=sys.stderr)


def fail(msg: str) -> NoReturn:
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


def detect_tools() -> List[Tool]:
    return [t for t in TOOLS if shutil.which(t.command) or t.home().is_dir()]


def select_tools(target: str) -> List[Tool]:
    if target == "all":
        return list(TOOLS)
    if target != "auto":
        return [t for t in TOOLS if t.key == target]
    found = detect_tools()
    if not found:
        info("Neither Claude Code nor Codex was detected; installing for both.")
        return list(TOOLS)
    return found


def local_source() -> Optional[Path]:
    """The clone this script lives in, or None when it was piped in from the network."""
    main_file = globals().get("__file__")
    if not main_file or main_file.startswith("<"):
        return None
    root = Path(main_file).resolve().parent
    return root if (root / SKILL_FILE).is_file() else None


def is_skill_path(parts: tuple) -> bool:
    if not parts or any(p in ("", ".", "..") for p in parts):
        return False
    return parts == (SKILL_FILE,) or (len(parts) > 1 and parts[0] in SKILL_DIRS)


def extract_archive(data: bytes, dest: Path) -> None:
    """Extract the skill files from a GitHub tarball (top-level dir stripped) into dest."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts[1:]
            if not is_skill_path(parts):
                continue
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            with src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    if not (dest / SKILL_FILE).is_file():
        fail("the downloaded archive does not contain {}.".format(SKILL_FILE))


def download_source(ref: str, workdir: Path) -> Path:
    url = "https://github.com/{}/archive/{}.tar.gz".format(REPO, ref)
    info("Downloading {} ...".format(url))
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ssl.SSLCertVerificationError) and sys.platform == "darwin":
            fail("SSL certificate verification failed. With the python.org installer, run "
                 "'Install Certificates.command' in your Python folder under /Applications, "
                 "or clone the repository and run install.py from it.")
        fail("download failed: {}".format(reason))
    dest = workdir / SKILL_NAME
    extract_archive(data, dest)
    return dest


def skill_name_of(path: Path) -> Optional[str]:
    """The `name:` in a SKILL.md frontmatter, if the file exists and has one."""
    try:
        text = (path / SKILL_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key.strip() == "name":
            return value.strip().strip("'\"")
    return None


def check_replaceable(dest: Path, force: bool) -> None:
    """Refuse to delete anything at dest that is not an installed copy of this skill."""
    if dest.is_symlink() or not dest.exists() or force:
        return
    if (dest / ".git").exists():
        fail("{} is a git clone; remove or move it yourself (or rerun with --force).".format(dest))
    if dest.is_dir() and skill_name_of(dest) == SKILL_NAME:
        return
    fail("{} exists and is not a {} skill; move it away or rerun with --force.".format(
        dest, SKILL_NAME))


def is_same_dir(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and os.path.samefile(str(a), str(b))
    except OSError:
        return False


def _make_writable_and_retry(func, path, _exc) -> None:
    # Windows refuses to delete read-only files.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_path(path: Path) -> None:
    if path.is_symlink():
        try:
            path.unlink()
        except OSError:
            os.rmdir(path)  # directory symlinks on some Windows setups
    elif path.is_dir():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_make_writable_and_retry)
        else:
            shutil.rmtree(path, onerror=_make_writable_and_retry)
    elif path.exists():
        path.unlink()


def copy_skill(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True)
    shutil.copy2(src / SKILL_FILE, dest / SKILL_FILE)
    for name in SKILL_DIRS:
        if (src / name).is_dir():
            shutil.copytree(src / name, dest / name,
                            ignore=shutil.ignore_patterns(".*", "__pycache__"))


def install_copy(src: Path, dest: Path) -> None:
    # Copy next to the destination first, so a failed copy leaves the old install intact.
    staging = Path(tempfile.mkdtemp(prefix=".{}-".format(SKILL_NAME), dir=str(dest.parent)))
    try:
        staged = staging / SKILL_NAME
        copy_skill(src, staged)
        remove_path(dest)
        os.replace(str(staged), str(dest))
    finally:
        remove_path(staging)


def install_link(src: Path, dest: Path) -> bool:
    """Symlink dest to src; False when the OS refuses (Windows without Developer Mode)."""
    remove_path(dest)
    try:
        os.symlink(str(src), str(dest), target_is_directory=True)
    except OSError as e:
        warn("could not create a symlink ({}); copying instead.".format(e))
        return False
    return True


def skills_dir_for(tool: Tool, project: Optional[Path]) -> Path:
    if project is None:
        return tool.user_skills()
    return project.joinpath(*tool.project_skills.split("/"))


def warn_duplicates(tool: Tool, dest: Path) -> None:
    if tool.key != "codex":
        return
    others = [Path.home() / ".agents" / "skills" / SKILL_NAME, codex_home() / "skills" / SKILL_NAME]
    for other in others:
        if other != dest and (other.exists() or other.is_symlink()):
            warn("Codex also loads {}; remove it to avoid two copies of the skill.".format(other))


def run_install(tools: List[Tool], src: Path, project: Optional[Path], link: bool,
                force: bool, dry_run: bool) -> None:
    for tool in tools:
        dest = skills_dir_for(tool, project) / SKILL_NAME
        existed = dest.exists() or dest.is_symlink()
        if not dest.is_symlink() and is_same_dir(dest, src):
            info("[{}] already in place (running from the installed directory) -> {}".format(
                tool.label, dest))
            continue
        check_replaceable(dest, force)
        if dry_run:
            action = "would update" if existed else "would install"
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if link and install_link(src, dest):
                action = "linked"
            else:
                install_copy(src, dest)
                action = "updated" if existed else "installed"
        info("[{}] {} -> {}".format(tool.label, action, dest))
        if project is None:
            warn_duplicates(tool, dest)


def run_uninstall(tools: List[Tool], project: Optional[Path], force: bool,
                  dry_run: bool) -> None:
    for tool in tools:
        dest = skills_dir_for(tool, project) / SKILL_NAME
        if not (dest.exists() or dest.is_symlink()):
            info("[{}] not installed at {}".format(tool.label, dest))
            continue
        check_replaceable(dest, force)
        if not dry_run:
            remove_path(dest)
        info("[{}] {} {}".format(tool.label, "would remove" if dry_run else "removed", dest))


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install the rust-elegant skill for Claude Code and Codex.")
    parser.add_argument("--target", choices=("auto", "claude", "codex", "all"), default="auto",
                        help="which tool to install for (default: auto, every tool detected)")
    parser.add_argument("--project", nargs="?", const=".", metavar="DIR",
                        help="install into project DIR (default: current directory) "
                             "instead of the user directory")
    parser.add_argument("--link", action="store_true",
                        help="symlink to this clone instead of copying (falls back to copy)")
    parser.add_argument("--uninstall", action="store_true", help="remove the skill")
    parser.add_argument("--force", action="store_true",
                        help="replace the destination even if it is not a rust-elegant skill")
    parser.add_argument("--ref", default=DEFAULT_REF,
                        help="branch or tag to download when not run from a clone "
                             "(default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="only print what would be done")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")  # non-ASCII paths on legacy consoles
        except (AttributeError, ValueError):
            pass

    args = parse_args(sys.argv[1:] if argv is None else argv)
    tools = select_tools(args.target)
    project = Path(args.project).expanduser().resolve() if args.project else None

    if args.uninstall:
        run_uninstall(tools, project, args.force, args.dry_run)
        return

    src = local_source()
    if src is not None:
        info("Source: {}".format(src))
        run_install(tools, src, project, args.link, args.force, args.dry_run)
    else:
        if args.link:
            fail("--link needs a local clone; run install.py from the cloned repository.")
        with tempfile.TemporaryDirectory() as tmp:
            src = download_source(args.ref, Path(tmp))
            run_install(tools, src, project, False, args.force, args.dry_run)

    if not args.dry_run:
        info("Done. Start a new Claude Code / Codex session if the skill does not show up.")


if __name__ == "__main__":
    main()
