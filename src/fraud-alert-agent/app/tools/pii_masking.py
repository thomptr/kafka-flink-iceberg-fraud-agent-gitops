import re

_CARD_RE = re.compile(r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?)(\d{4})\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")


def mask_pii(value: str | dict | list) -> str | dict | list:
    if isinstance(value, dict):
        return {k: mask_pii(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_pii(item) for item in value]
    if not isinstance(value, str):
        return value
    value = _CARD_RE.sub(lambda m: f"****-****-****-{m.group(2)}", value)
    value = _SSN_RE.sub("***-**-****", value)
    value = _EMAIL_RE.sub("[email redacted]", value)
    return value
