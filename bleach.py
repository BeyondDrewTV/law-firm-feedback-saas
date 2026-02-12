"""Local fallback shim for bleach.clean."""
import html

def clean(text, strip=True, **kwargs):
    value = '' if text is None else str(text)
    escaped = html.escape(value, quote=True)
    return escaped
