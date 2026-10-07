''' Application settings.

    Defaults come from astropipes.config.defaults; user values override them from
    $XDG_CONFIG_HOME/astropipes/config.toml (or $ASTROPIPES_CONFIG). Values are read at
    attribute access time, so settings.reload() after the Settings dialog takes effect
    everywhere that reads settings.X at call time.

    Usage:
        from astropipes.config import settings
        settings.DATA_PATH
'''

import os
import runpy
import sys
import tomllib
from pathlib import Path

from astropipes.config import defaults


def _config_path() -> Path:
    explicit = os.environ.get('ASTROPIPES_CONFIG')
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config'
    return Path(base) / 'astropipes' / 'config.toml'


CONFIG_PATH = _config_path()

# config.py at the repository root, used by versions before the TOML settings file
_LEGACY_CONFIG_PY = Path(__file__).resolve().parents[2] / 'config.py'

DEFAULTS = {k: v for k, v in vars(defaults).items() if k.isupper()}

# Always written to the settings file, even when equal to the default, so it shows where data lives
PATH_KEYS = ('DATA_PATH', 'CALIBRATION_PATH', 'STACKS_PATH', 'ARCHIVE_PATH', 'PROCESSED_PATH',
             'DATABASE_PATH')


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (list, tuple)):
        return '[' + ', '.join(_toml_value(v) for v in value) + ']'
    if isinstance(value, dict):
        return '{ ' + ', '.join(f'"{k}" = {_toml_value(v)}' for k, v in value.items()) + ' }'
    raise TypeError(f"Cannot write {type(value).__name__} to TOML")


def _coerce(key: str, value):
    """Match the type of the default (TOML has no int/float distinction for 4e9)."""
    default = DEFAULTS[key]
    if isinstance(default, float) and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


class Settings:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self._values = {}
        self.reload()

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(f"Unknown setting: {name}") from None

    def reload(self):
        """Re-read the settings file (e.g. after it was saved)."""
        if not self.path.exists() and _LEGACY_CONFIG_PY.exists():
            self._import_legacy_config_py()
        values = dict(DEFAULTS)
        values.update(self._read_overrides())
        self._values = values

    def overrides(self) -> dict:
        """Values set in the settings file (only keys that differ from the defaults)."""
        return self._read_overrides()

    def save(self, updates: dict):
        """Write updates to the settings file and reload. Values equal to the default are dropped
        (except PATH_KEYS)."""
        overrides = self._read_overrides()
        for key, value in updates.items():
            if key not in DEFAULTS:
                raise KeyError(f"Unknown setting: {key}")
            if value == DEFAULTS[key] and key not in PATH_KEYS:
                overrides.pop(key, None)
            else:
                overrides[key] = value
        self._write(overrides)
        self.reload()

    def _read_overrides(self) -> dict:
        if not self.path.exists():
            return {}
        with open(self.path, 'rb') as f:
            data = tomllib.load(f)
        overrides = {}
        for key, value in data.items():
            if key in DEFAULTS:
                overrides[key] = _coerce(key, value)
            else:
                print(f"Warning: ignoring unknown setting {key} in {self.path}", file=sys.stderr)
        return overrides

    def _write(self, overrides: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = ['# Astropipes settings. Keys not listed here use the defaults from',
                 '# astropipes/config/defaults.py.', '']
        lines += [f'{key} = {_toml_value(overrides[key])}' for key in DEFAULTS if key in overrides]
        tmp = self.path.with_suffix('.toml.tmp')
        tmp.write_text('\n'.join(lines) + '\n')
        tmp.replace(self.path)

    def _import_legacy_config_py(self):
        """One-time import of values from the old config.py into the settings file."""
        legacy = runpy.run_path(str(_LEGACY_CONFIG_PY))
        overrides = {k: _coerce(k, v) for k, v in legacy.items()
                     if k in DEFAULTS and (v != DEFAULTS[k] or k in PATH_KEYS)}
        self._write(overrides)
        print(f"Imported settings from {_LEGACY_CONFIG_PY} into {self.path}", file=sys.stderr)


settings = Settings()
