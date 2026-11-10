"""설정과 단축키 파싱.

설정은 환경변수로 들어온다. Claude 데스크톱에 번들로 설치하면 manifest.json의
user_config 값이 환경변수로 전달된다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# RegisterHotKey 수식키 플래그
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
}

_NAMED_KEYS = {
    "space": 0x20,
    "printscreen": 0x2C,
    "prtsc": 0x2C,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "pause": 0x13,
    "scrolllock": 0x91,
}

# 수식키 없이 단독으로 써도 되는 키 (글자·숫자 단독은 타이핑을 가로채므로 금지)
_STANDALONE_OK = set(range(0x70, 0x88)) | {0x2C, 0x13, 0x91}

DEFAULT_SELECT_HOTKEY = "Ctrl+Alt+A"
DEFAULT_ACTIVE_HOTKEY = "Ctrl+Alt+W"
MAX_IMAGES_PER_MESSAGE = 20  # claude.ai 한 메시지 이미지 상한


class HotkeyError(ValueError):
    """단축키 문자열을 해석할 수 없을 때."""


@dataclass(frozen=True)
class Hotkey:
    text: str  # 사람이 읽는 정규화된 표기 (예: "Ctrl+Alt+A")
    modifiers: int  # MOD_* 비트 (MOD_NOREPEAT 제외)
    vk: int  # 가상 키 코드


def parse_hotkey(spec: str) -> Hotkey:
    """'Ctrl+Alt+A' 같은 문자열을 RegisterHotKey 인자로 바꾼다."""
    if spec is None or not str(spec).strip():
        raise HotkeyError("단축키가 비어 있어요")
    parts = [p.strip() for p in str(spec).split("+")]
    if any(p == "" for p in parts):
        raise HotkeyError(f"'{spec}': '+' 사이에 빈 키가 있어요")

    mods = 0
    mod_names: list[str] = []
    key_vk: int | None = None
    key_name = ""
    for raw in parts:
        low = raw.lower()
        if low in _MODIFIERS:
            bit = _MODIFIERS[low]
            if mods & bit:
                raise HotkeyError(f"'{spec}': 수식키 '{raw}'가 두 번 들어갔어요")
            mods |= bit
            continue
        if key_vk is not None:
            raise HotkeyError(f"'{spec}': 일반 키는 하나만 쓸 수 있어요")
        key_vk, key_name = _parse_key(raw, spec)

    if key_vk is None:
        raise HotkeyError(f"'{spec}': 수식키 외에 일반 키가 하나 필요해요")
    if mods == 0 and key_vk not in _STANDALONE_OK:
        raise HotkeyError(f"'{spec}': 글자·숫자 키는 Ctrl/Alt/Shift/Win과 함께 써야 해요")
    if mods == MOD_SHIFT and key_vk not in _STANDALONE_OK:
        raise HotkeyError(f"'{spec}': Shift+글자는 대문자 입력과 겹쳐요. Ctrl이나 Alt를 함께 쓰세요")

    order = [(MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win")]
    mod_names = [name for bit, name in order if mods & bit]
    text = "+".join(mod_names + [key_name])
    return Hotkey(text=text, modifiers=mods, vk=key_vk)


def _parse_key(raw: str, spec: str) -> tuple[int, str]:
    low = raw.lower()
    if len(raw) == 1 and raw.isascii() and raw.isalnum():
        ch = raw.upper()
        return ord(ch), ch
    m = re.fullmatch(r"f([0-9]{1,2})", low)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 24:
            return 0x70 + n - 1, f"F{n}"
        raise HotkeyError(f"'{spec}': F1~F24만 쓸 수 있어요")
    if low in _NAMED_KEYS:
        pretty = {"prtsc": "PrintScreen", "ins": "Insert", "pgup": "PageUp", "pgdn": "PageDown"}.get(
            low, raw[:1].upper() + raw[1:]
        )
        return _NAMED_KEYS[low], pretty
    raise HotkeyError(f"'{spec}': '{raw}'는 알 수 없는 키예요")


def _clean_env(value: str | None) -> str:
    """번들 설정에서 값이 비면 '${user_config.x}'가 그대로 넘어올 수 있어 빈 값으로 본다."""
    if value is None:
        return ""
    value = value.strip()
    if re.fullmatch(r"\$\{[^}]*\}", value):
        return ""
    return value


def _parse_bool(value: str, default: bool) -> bool:
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on", "예"):
        return True
    if v in ("0", "false", "no", "off", "아니오"):
        return False
    return default


@dataclass
class Settings:
    select_hotkey: Hotkey
    active_hotkey: Hotkey
    capture_dir_override: str = ""
    auto_paste: bool = True
    problems: list[str] = field(default_factory=list)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """환경변수에서 설정을 읽는다. 잘못된 값은 기본값으로 되돌리고 problems에 남긴다."""
    env = dict(os.environ if env is None else env)
    problems: list[str] = []

    def hotkey_from(name: str, default: str) -> Hotkey:
        raw = _clean_env(env.get(name))
        if not raw:
            return parse_hotkey(default)
        try:
            return parse_hotkey(raw)
        except HotkeyError as e:
            problems.append(f"{name}: {e} → 기본값 {default} 사용")
            return parse_hotkey(default)

    select = hotkey_from("SNIP_HOTKEY_SELECT", DEFAULT_SELECT_HOTKEY)
    active = hotkey_from("SNIP_HOTKEY_ACTIVE", DEFAULT_ACTIVE_HOTKEY)
    if (select.modifiers, select.vk) == (active.modifiers, active.vk):
        problems.append(
            f"두 단축키가 같아요({select.text}) → 활성 창 단축키를 기본값으로 바꿨어요"
        )
        active = parse_hotkey(DEFAULT_ACTIVE_HOTKEY)
        if (select.modifiers, select.vk) == (active.modifiers, active.vk):
            active = parse_hotkey(DEFAULT_SELECT_HOTKEY)

    return Settings(
        select_hotkey=select,
        active_hotkey=active,
        capture_dir_override=_clean_env(env.get("SNIP_CAPTURE_DIR")),
        auto_paste=_parse_bool(_clean_env(env.get("SNIP_AUTO_PASTE")) or "true", True),
        problems=problems,
    )
