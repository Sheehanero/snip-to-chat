"""캡처 저장. 저장 폴더가 git 저장소 안이면 저장을 거부한다.

캡처가 공개 저장소에 섞여 올라가는 것을 막는 것이 이 모듈의 첫 번째 일이다.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import APP_NAME
from .imaging import to_png_bytes

KEEP_FILES = 200  # 오래된 캡처는 이 개수만 남기고 지운다


class UnsafeCaptureDir(RuntimeError):
    """저장 폴더가 git 저장소 안에 있을 때."""


def find_git_root(path: Path) -> Path | None:
    """path 자신이나 상위 폴더 중 .git(폴더 또는 파일)이 있는 곳을 찾는다.

    아직 만들어지지 않은 폴더도 검사할 수 있게, 존재하는 가장 가까운 상위부터 본다.
    """
    p = Path(os.path.abspath(path))
    for candidate in [p, *p.parents]:
        try:
            if (candidate / ".git").exists():
                return candidate
        except OSError:
            continue
    return None


def default_capture_dir(env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ if env is None else env)
    base = env.get("LOCALAPPDATA") or env.get("XDG_DATA_HOME")
    if not base:
        base = str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME / "captures"


def resolve_capture_dir(override: str, env: dict[str, str] | None = None) -> Path:
    if override:
        return Path(os.path.expandvars(os.path.expanduser(override)))
    return default_capture_dir(env)


def check_capture_dir(path: Path) -> tuple[bool, str]:
    """(안전한지, 이유). 안전하지 않으면 저장하지 않는다."""
    root = find_git_root(path)
    if root is not None:
        return False, f"저장 폴더가 git 저장소({root}) 안에 있어서 저장하지 않아요"
    return True, "git 저장소 밖"


@dataclass
class SavedCapture:
    path: Path | None
    reason: str


class CaptureStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.safe, self.reason = check_capture_dir(directory)

    def save(self, img: Image.Image, kind: str, now: _dt.datetime | None = None) -> SavedCapture:
        # 저장할 때마다 다시 검사한다 (실행 중에 누가 그 위치에 git init을 할 수도 있다).
        self.safe, self.reason = check_capture_dir(self.directory)
        if not self.safe:
            return SavedCapture(None, self.reason)
        self.directory.mkdir(parents=True, exist_ok=True)
        now = now or _dt.datetime.now()
        stem = now.strftime("%Y%m%d-%H%M%S-") + f"{now.microsecond // 1000:03d}-{_safe_kind(kind)}"
        path = self.directory / f"{stem}.png"
        n = 1
        while path.exists():
            path = self.directory / f"{stem}-{n}.png"
            n += 1
        path.write_bytes(to_png_bytes(img))
        self.prune()
        return SavedCapture(path, "저장됨")

    def prune(self, keep: int = KEEP_FILES) -> int:
        if not self.directory.is_dir():
            return 0
        files = sorted(
            (p for p in self.directory.glob("*.png") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        removed = 0
        for old in files[keep:]:
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
        return removed


USER_KINDS = ("window", "region", "active", "tab")


def recent_capture_files(directory: Path, count: int) -> list[Path]:
    """사용자가 단축키로 찍은 캡처 파일을 최신순으로 (자체 점검·도구로 찍은 것은 뺀다)."""
    if not directory.is_dir():
        return []
    files = [
        p for p in directory.glob("*.png")
        if p.is_file() and any(p.stem.endswith("-" + k) or f"-{k}-" in p.stem for k in USER_KINDS)
    ]
    files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return files[:count]


def _safe_kind(kind: str) -> str:
    return "".join(c for c in kind if c.isalnum() or c in "-_")[:20] or "capture"
