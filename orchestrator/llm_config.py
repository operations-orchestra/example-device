"""Where the LLM brain's endpoints come from: named profiles, and keys kept apart from them.

Profiles: ``$ORCHESTRA_LLM_CONFIG`` if set, else ``config/llm.yaml`` in the repository, which
git ignores. The repository tracks only ``config/llm.example.yaml``; copy it to start::

    default: gateway
    profiles:
      gateway:
        backend: openai_compatible
        options: {base_url: "https://llm-gateway.example.org/v1", model: some-model,
                  api_key_env: GATEWAY_API_KEY}

Keys: never in a profiles file. A profile names the variable that holds its key
(``api_key_env``); its value is looked up, in order, in the environment, then in
``~/.config/orchestra/keys.env`` (``NAME=value`` lines; ``$ORCHESTRA_KEYS_FILE`` overrides),
which must be readable only by its owner. ``api_key_keychain`` names a macOS Keychain entry
instead. Keys are read only when a profile is used and sent only to its own endpoint.
"""
from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
BACKENDS = ("openai_compatible",)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    backend: str
    base_url: str
    model: str
    api_key_env: str = ""
    api_key_keychain: str = ""
    extra: dict = field(default_factory=dict)

    def key_source(self) -> str:
        """Where the key comes from, for display. Never the key itself."""
        if self.api_key_env:
            return f"{self.api_key_env} (environment or {keys_path()})"
        if self.api_key_keychain:
            return f"Keychain entry {self.api_key_keychain}"
        return "none needed"

    def api_key(self) -> str:
        """The key, read now. Raises if the profile names a source and it is empty."""
        if self.api_key_env:
            key = os.environ.get(self.api_key_env, "") or read_keys_file().get(self.api_key_env, "")
            if key:
                return key
            if not self.api_key_keychain:
                raise ConfigError(f"profile {self.name!r}: {self.api_key_env} is set neither in the environment "
                                  f"nor in {keys_path()}")
        if self.api_key_keychain:
            try:
                out = subprocess.run(["security", "find-generic-password", "-s", self.api_key_keychain, "-w"],
                                     capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ConfigError(f"profile {self.name!r}: cannot read the Keychain ({exc.__class__.__name__})") from None
            if out.returncode != 0 or not out.stdout.strip():
                raise ConfigError(f"profile {self.name!r}: no Keychain entry {self.api_key_keychain!r}")
            return out.stdout.strip()
        return ""

    def key_available(self) -> bool:
        try:
            return bool(self.api_key()) or not (self.api_key_env or self.api_key_keychain)
        except ConfigError:
            return False

    def key_problem(self) -> str:
        """Why the key cannot be read, or empty."""
        try:
            self.api_key()
            return ""
        except ConfigError as exc:
            return str(exc)

    def describe(self) -> dict[str, Any]:
        """Safe to show anywhere: no key."""
        host = urlparse(self.base_url).netloc or self.base_url
        return {"name": self.name, "backend": self.backend, "host": host, "model": self.model,
                "key_source": self.key_source(), "key_available": self.key_available()}


def config_path() -> Path:
    return Path(os.environ.get("ORCHESTRA_LLM_CONFIG", str(REPO / "config" / "llm.yaml"))).expanduser()


def keys_path() -> Path:
    return Path(os.environ.get("ORCHESTRA_KEYS_FILE", "~/.config/orchestra/keys.env")).expanduser()


def read_keys_file() -> dict[str, str]:
    """``NAME=value`` lines from the keys file. Refused if anyone but its owner can read it."""
    path = keys_path()
    if not path.is_file():
        return {}
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(f"{path} can be read by others; run: chmod 600 {path}")
    keys = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.removeprefix("export ").split("=", 1)
            keys[name.strip()] = value.strip().strip('"').strip("'")
    return keys


def load_profiles(path: Optional[Path] = None) -> tuple[dict[str, Profile], Optional[str]]:
    """All profiles that can drive the LLM brain, and the default's name. Missing file: none."""
    import yaml

    path = path or config_path()
    if not path.is_file():
        return {}, None
    data = yaml.safe_load(path.read_text()) or {}
    profiles: dict[str, Profile] = {}
    for name, spec in (data.get("profiles") or {}).items():
        spec = spec or {}
        backend = spec.get("backend", "")
        if backend not in BACKENDS:
            continue                      # e.g. "mock" in a shared file: not an LLM brain here
        opts = dict(spec.get("options") or {})
        if "api_key" in opts:
            raise ConfigError(f"profile {name!r} puts a key in the file; use api_key_env or api_key_keychain instead")
        try:
            profiles[name] = Profile(
                name=name, backend=backend, base_url=str(opts.pop("base_url")), model=str(opts.pop("model")),
                api_key_env=str(opts.pop("api_key_env", "")), api_key_keychain=str(opts.pop("api_key_keychain", "")),
                extra=opts)
        except KeyError as exc:
            raise ConfigError(f"profile {name!r} needs {exc.args[0]}") from None
    default = data.get("default")
    return profiles, default if default in profiles else None


def get_profile(name: Optional[str] = None, path: Optional[Path] = None) -> Profile:
    profiles, default = load_profiles(path)
    if not profiles:
        raise ConfigError(f"no LLM profiles in {config_path()}: copy config/llm.example.yaml to it and edit it")
    chosen = name or default or (next(iter(profiles)) if len(profiles) == 1 else None)
    if chosen is None:
        raise ConfigError(f"several profiles and no default: name one of {sorted(profiles)}")
    if chosen not in profiles:
        raise ConfigError(f"no profile {chosen!r}; profiles: {sorted(profiles)}")
    return profiles[chosen]
