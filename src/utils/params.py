"""Loads params.yaml; missing file/keys fall back to in-code defaults."""
from functools import lru_cache
import yaml
from config.settings import settings

PARAMS_FILE = settings.BASE_DIR / 'params.yaml'


@lru_cache(maxsize=1)
def load_params() -> dict:
    try:
        with open(PARAMS_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def get_param(section: str, key: str, default):
    return (load_params().get(section) or {}).get(key, default)
