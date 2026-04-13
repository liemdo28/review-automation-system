from __future__ import annotations

from typing import Any


STORE_THEME_MAP = {
    "raw-sushi-stockton": {
        "accent": "#3cc6ff",
        "accent_soft": "rgba(60, 198, 255, 0.16)",
        "border": "rgba(60, 198, 255, 0.34)",
        "label": "Stockton blue",
    },
    "bakudan-bandera": {
        "accent": "#ff9f40",
        "accent_soft": "rgba(255, 159, 64, 0.16)",
        "border": "rgba(255, 159, 64, 0.34)",
        "label": "Bandera amber",
    },
    "bakudan-stone-oak": {
        "accent": "#7de38d",
        "accent_soft": "rgba(125, 227, 141, 0.16)",
        "border": "rgba(125, 227, 141, 0.34)",
        "label": "Stone Oak green",
    },
    "bakudan-rim": {
        "accent": "#ff5f8f",
        "accent_soft": "rgba(255, 95, 143, 0.16)",
        "border": "rgba(255, 95, 143, 0.34)",
        "label": "The Rim rose",
    },
    "bakudan-ramen": {
        "accent": "#ff7d66",
        "accent_soft": "rgba(255, 125, 102, 0.16)",
        "border": "rgba(255, 125, 102, 0.34)",
        "label": "Bakudan ember",
    },
}

DEFAULT_THEME = {
    "accent": "#b88cff",
    "accent_soft": "rgba(184, 140, 255, 0.16)",
    "border": "rgba(184, 140, 255, 0.34)",
    "label": "Default accent",
}


def store_theme_for_location(location: Any | None) -> dict[str, str]:
    slug = getattr(location, "slug", None)
    if slug and slug in STORE_THEME_MAP:
        return STORE_THEME_MAP[slug]
    return DEFAULT_THEME


def store_theme_style(location: Any | None) -> str:
    theme = store_theme_for_location(location)
    return (
        f"--store-accent: {theme['accent']}; "
        f"--store-accent-soft: {theme['accent_soft']}; "
        f"--store-accent-border: {theme['border']};"
    )
