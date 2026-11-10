import datetime as dt
import os
import subprocess

import pytest
from PIL import Image

from snip_to_chat.storage import (
    CaptureStore,
    check_capture_dir,
    default_capture_dir,
    find_git_root,
    resolve_capture_dir,
)


def test_default_dir_uses_localappdata(tmp_path):
    d = default_capture_dir({"LOCALAPPDATA": str(tmp_path)})
    assert d == tmp_path / "snip-to-chat" / "captures"


def test_dir_inside_repo_is_refused(tmp_path):
    repo = tmp_path / "snip-to-chat"
    (repo / ".git").mkdir(parents=True)
    ok, reason = check_capture_dir(repo / "captures")  # 아직 없는 하위 폴더도 거부
    assert not ok and "git" in reason


def test_repo_root_itself_is_refused(tmp_path):
    (tmp_path / ".git").mkdir()
    assert not check_capture_dir(tmp_path)[0]


def test_worktree_git_file_is_refused(tmp_path):
    # git worktree나 submodule은 .git이 폴더가 아니라 파일이다
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
    assert find_git_root(tmp_path / "a" / "b") == tmp_path
    assert not check_capture_dir(tmp_path / "a")[0]


def test_dir_outside_repo_is_ok(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    ok, _ = check_capture_dir(tmp_path / "appdata" / "snip-to-chat" / "captures")
    assert ok


def test_relative_dotdot_path_is_resolved(tmp_path, monkeypatch):
    # 'captures/../..' 같이 써도 실제 위치로 판단해야 한다
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    outside = tmp_path / "out"
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert not check_capture_dir(os.path.join("..", "repo", "x"))[0]


def test_save_refuses_inside_repo_and_writes_nothing(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    store = CaptureStore(repo / "captures")
    saved = store.save(Image.new("RGB", (10, 10)), "window")
    assert saved.path is None
    assert not (repo / "captures").exists()


def test_save_rechecks_when_repo_appears_later(tmp_path):
    d = tmp_path / "caps"
    store = CaptureStore(d)
    assert store.save(Image.new("RGB", (5, 5)), "region").path is not None
    (tmp_path / ".git").mkdir()  # 실행 중에 상위에서 git init
    assert store.save(Image.new("RGB", (5, 5)), "region").path is None


def test_save_unique_names_same_millisecond(tmp_path):
    store = CaptureStore(tmp_path / "caps")
    now = dt.datetime(2026, 11, 10, 11, 30, 0, 123000)
    a = store.save(Image.new("RGB", (5, 5)), "win/../evil", now=now).path
    b = store.save(Image.new("RGB", (5, 5)), "win/../evil", now=now).path
    assert a != b and a.parent == b.parent == tmp_path / "caps"  # 경로 문자 제거됨


def test_prune_keeps_newest(tmp_path):
    store = CaptureStore(tmp_path / "caps")
    paths = []
    for i in range(5):
        p = store.save(Image.new("RGB", (2, 2)), "x", now=dt.datetime(2026, 1, 1, 0, 0, i)).path
        os.utime(p, (1_000_000 + i, 1_000_000 + i))
        paths.append(p)
    assert store.prune(keep=2) == 3
    left = sorted(p.name for p in (tmp_path / "caps").glob("*.png"))
    assert left == sorted(p.name for p in paths[-2:])


def test_override_expands_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows는 HOME 대신 이것을 본다
    assert resolve_capture_dir("~/pics") == tmp_path / "pics"


@pytest.mark.skipif(subprocess.run(["git", "--version"], capture_output=True).returncode != 0, reason="git 없음")
def test_gitignore_blocks_captures_but_allows_assets(tmp_path):
    """저장소 .gitignore가 캡처 이미지는 막고 assets/ 아이콘은 허용하는지 실제 git으로 확인."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if not (root / ".git").exists():
        pytest.skip("git 저장소 밖에서 실행됨")

    def ignored(rel: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", rel], cwd=root).returncode == 0

    for rel in [
        "capture.png",
        "captures/20261110-window.png",
        "docs/screenshot.jpg",
        "tests/data/x.webp",
        "src/snip_to_chat/shot.bmp",
        "selftest-report.json",
        "snip-to-chat.mcpb",
        "bundle/server/snip-to-chat.exe",
    ]:
        assert ignored(rel), rel
    for rel in ["assets/icon.png", "assets/sub/logo.png", "src/snip_to_chat/config.py", "manifest.json"]:
        assert not ignored(rel), rel
