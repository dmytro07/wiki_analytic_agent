"""English names of common Wikipedia language editions, and spotting them in text."""

from __future__ import annotations

import re

NAMES = {
    "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali", "ca": "Catalan", "cs": "Czech", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish", "et": "Estonian", "fa": "Persian",
    "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "hu": "Hungarian",
    "hy": "Armenian", "id": "Indonesian", "it": "Italian", "ja": "Japanese", "ka": "Georgian", "kk": "Kazakh",
    "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian", "ms": "Malay", "nl": "Dutch", "no": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sco": "Scots", "sk": "Slovak",
    "sl": "Slovenian", "sr": "Serbian", "sv": "Swedish", "sw": "Swahili", "th": "Thai", "tr": "Turkish",
    "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek", "vi": "Vietnamese", "zh": "Chinese",
}
# Codes that are also everyday English words: only matched as 'itwiki', 'it.wikipedia' or '(it)'.
AMBIGUOUS_CODES = {"am", "an", "as", "be", "he", "hi", "id", "is", "it", "la", "ms", "my", "no", "or", "so", "to"}


def language_name(code: str) -> str:
    return NAMES.get(code, code)


def mentions(text: str, code: str) -> bool:
    low = text.lower()
    c = re.escape(code)
    patterns = [rf"\b{c}wiki\b", rf"\b{c}\.wikipedia", rf"\({c}\)"]
    if code not in AMBIGUOUS_CODES:
        patterns.append(rf"\b{c}\b")
    if code in NAMES:
        patterns.append(rf"\b{re.escape(NAMES[code].lower())}\b")
    return any(re.search(p, low) for p in patterns)
