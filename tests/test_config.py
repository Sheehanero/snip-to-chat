import pytest

from snip_to_chat.config import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    HotkeyError,
    load_settings,
    parse_hotkey,
)


@pytest.mark.parametrize(
    "spec, mods, vk, text",
    [
        ("Ctrl+Alt+A", MOD_CONTROL | MOD_ALT, 0x41, "Ctrl+Alt+A"),
        ("alt + ctrl + a", MOD_CONTROL | MOD_ALT, 0x41, "Ctrl+Alt+A"),  # 순서·대소문자·공백 무관
        ("Ctrl+Shift+1", MOD_CONTROL | MOD_SHIFT, 0x31, "Ctrl+Shift+1"),
        ("F12", 0, 0x7B, "F12"),  # F키는 단독 허용
        ("Win+Shift+F24", MOD_WIN | MOD_SHIFT, 0x87, "Shift+Win+F24"),
        ("PrtSc", 0, 0x2C, "PrintScreen"),
        ("Ctrl+Space", MOD_CONTROL, 0x20, "Ctrl+Space"),
    ],
)
def test_parse_ok(spec, mods, vk, text):
    hk = parse_hotkey(spec)
    assert (hk.modifiers, hk.vk, hk.text) == (mods, vk, text)


@pytest.mark.parametrize(
    "spec",
    [
        "",
        "   ",
        "Ctrl+",  # 빈 키
        "Ctrl++A",
        "Ctrl+Ctrl+A",  # 수식키 중복
        "Ctrl+Alt",  # 일반 키 없음
        "A",  # 글자 단독은 타이핑을 가로챔
        "Shift+A",  # 대문자 입력과 겹침
        "Ctrl+A+B",  # 일반 키 두 개
        "Ctrl+F25",
        "Ctrl+F0",
        "Ctrl+한",  # 알 수 없는 키
        "Ctrl+ㅁ",
    ],
)
def test_parse_rejects(spec):
    with pytest.raises(HotkeyError):
        parse_hotkey(spec)


def test_settings_defaults():
    s = load_settings({})
    assert s.select_hotkey.text == "Ctrl+Alt+A"
    assert s.active_hotkey.text == "Ctrl+Alt+W"
    assert s.auto_paste is True
    assert s.capture_dir_override == ""
    assert s.problems == []


def test_unsubstituted_placeholder_is_treated_as_empty():
    # 번들 설정 값이 비면 '${user_config.x}'가 그대로 들어올 수 있다
    s = load_settings(
        {
            "SNIP_HOTKEY_SELECT": "${user_config.select_hotkey}",
            "SNIP_CAPTURE_DIR": "${user_config.capture_dir}",
            "SNIP_AUTO_PASTE": "${user_config.auto_paste}",
        }
    )
    assert s.select_hotkey.text == "Ctrl+Alt+A"
    assert s.capture_dir_override == ""
    assert s.auto_paste is True
    assert s.problems == []


def test_bad_hotkey_falls_back_and_reports():
    s = load_settings({"SNIP_HOTKEY_SELECT": "A"})
    assert s.select_hotkey.text == "Ctrl+Alt+A"
    assert s.problems and "SNIP_HOTKEY_SELECT" in s.problems[0]


def test_same_hotkeys_are_separated():
    s = load_settings({"SNIP_HOTKEY_SELECT": "Ctrl+Alt+W", "SNIP_HOTKEY_ACTIVE": "ctrl+alt+w"})
    assert (s.select_hotkey.modifiers, s.select_hotkey.vk) != (
        s.active_hotkey.modifiers,
        s.active_hotkey.vk,
    )
    assert s.problems


def test_same_hotkeys_when_select_is_default_active():
    # 선택 단축키를 '활성 창 기본값'으로 바꾸고 활성 창도 같게 두면, 되돌린 값도 겹친다
    s = load_settings({"SNIP_HOTKEY_SELECT": "Ctrl+Alt+W"})
    assert (s.select_hotkey.modifiers, s.select_hotkey.vk) != (
        s.active_hotkey.modifiers,
        s.active_hotkey.vk,
    )


@pytest.mark.parametrize("v, expected", [("false", False), ("0", False), ("TRUE", True), ("garbage", True)])
def test_auto_paste_parse(v, expected):
    assert load_settings({"SNIP_AUTO_PASTE": v}).auto_paste is expected
