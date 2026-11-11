import re
from urllib.parse import urlsplit, urlunsplit

SKILL_ALIASES: dict[str, tuple[str, str]] = {
    "c": ("C", "language"),
    "c++": ("C++", "language"),
    "c/c++": ("C/C++", "language"),
    "python": ("Python", "language"),
    "javascript": ("JavaScript", "language"),
    "typescript": ("TypeScript", "language"),
    "sql": ("SQL", "language"),
    "matlab": ("MATLAB", "language"),
    "html/css": ("HTML/CSS", "language"),
    "networkx": ("NetworkX", "ml_tooling"),
    "pandas": ("pandas", "ml_tooling"),
    "scikit-learn": ("scikit-learn", "ml_tooling"),
    "numpy": ("NumPy", "ml_tooling"),
    "tensorflow lite micro": ("TensorFlow Lite Micro", "ml_systems"),
    "freertos": ("FreeRTOS", "embedded"),
    "esp32": ("ESP32", "embedded"),
    "esp32-s3": ("ESP32-S3", "embedded"),
    "react": ("React", "framework"),
    "vite": ("Vite", "framework"),
    "fastapi": ("FastAPI", "backend"),
    "flask": ("Flask", "backend"),
    "docker": ("Docker", "platform"),
    "websocket": ("WebSocket", "backend"),
    "rest apis": ("REST APIs", "backend"),
    "git": ("Git", "developer_tool"),
    "linux": ("Linux", "developer_tool"),
    "kicad": ("KiCad", "hardware"),
    "kicad scripting api": ("KiCad Scripting API", "hardware"),
    "ply (lex-yacc)": ("PLY", "compiler"),
    "ply (python lex-yacc)": ("PLY", "compiler"),
    "ast construction": ("AST construction", "compiler"),
    "dsl design": ("DSL design", "compiler"),
    "sha-256": ("SHA-256", "security"),
}


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def normalize_skill(value: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", value).strip().strip(".")
    return SKILL_ALIASES.get(cleaned.casefold(), (cleaned, "other"))


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, parts.query, ""))
