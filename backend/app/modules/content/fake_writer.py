"""Offline writer for LLM_PROVIDER=fake (tests, local development, demos without a key).

It answers the writing tasks the way the model is asked to: one sentence per fact, each
citing its fact, in every requested language, padded with warm closing lines that state
nothing (no numbers, names or results) until the task's word range is met. English uses
the fact claims as they are; Finnish and Bengali use simple frames around the fact's
team name and numbers. It is not meant to read well, only to exercise the pipeline.
"""

import json
import re
from collections.abc import Callable
from typing import Any

from app.core.config import Settings
from app.core.llm import FakeProvider, LLMProvider

_DIGITS = re.compile(r"\d+")
_BENGALI = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_WRITING_TASKS = ("report", "preview", "team_recap", "summary", "announcement", "commentary")
_SKIP = ("kickoff", "pitch", "reason", "win_chance")
_WARM = {
    "en": [
        "Families and friends along the touchline cheered every moment of the day.",
        "The volunteers kept everything running smoothly from start to finish.",
        "Everyone who came made this a proud day for the whole community.",
        "The players gave their best and showed real team spirit on the pitch.",
        "It was a day to remember for everyone who loves this game.",
    ],
    "fi": [
        "Perheet ja ystävät kannustivat joukkueita koko päivän ajan.",
        "Vapaaehtoiset pitivät huolen siitä, että kaikki sujui hyvin alusta loppuun.",
        "Jokainen paikalla ollut teki päivästä hienon koko yhteisölle.",
        "Pelaajat antoivat kaikkensa ja näyttivät upeaa joukkuehenkeä kentällä.",
        "Päivä jää mieleen kaikille, jotka rakastavat tätä peliä.",
    ],
    "bn": [
        "মাঠের পাশে পরিবার ও বন্ধুরা সারাদিন খেলোয়াড়দের উৎসাহ দিয়েছেন।",
        "স্বেচ্ছাসেবকেরা শুরু থেকে শেষ পর্যন্ত সবকিছু সুন্দরভাবে পরিচালনা করেছেন।",
        "যারা এসেছেন তারা সবাই মিলে দিনটিকে পুরো সমাজের জন্য গর্বের করে তুলেছেন।",
        "খেলোয়াড়েরা মাঠে নিজেদের সেরাটা দিয়েছেন এবং দারুণ দলগত মনোভাব দেখিয়েছেন।",
        "এই খেলাকে যারা ভালোবাসেন তাদের সবার কাছে দিনটি স্মরণীয় হয়ে থাকবে।",
    ],
}


def _inputs(prompt: str) -> tuple[list[str], dict[str, Any]]:
    languages = re.search(r"Languages: (.*)", prompt)
    payload = prompt.split("<inputs>", 1)[1].split("</inputs>", 1)[0]
    langs = [lang.strip() for lang in languages.group(1).split(",")] if languages else ["en"]
    return langs, json.loads(payload)


def _numbers(fact: dict[str, Any]) -> list[str]:
    value = fact.get("value")
    if isinstance(value, str) and _DIGITS.search(value):
        return _DIGITS.findall(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return [str(value)]
    return []


def _sentence(fact: dict[str, Any], language: str) -> str | None:
    if language == "en":
        return f"{fact['claim']}."
    numbers = _numbers(fact)
    if not numbers:
        return None  # names and status words need the real model in fi and bn
    if language == "fi":
        return f"Ottelun tiedoissa luku on {'-'.join(numbers)}."
    return f"খেলার তথ্যে সংখ্যাটি {'-'.join(numbers).translate(_BENGALI)}।"


def _text(facts: list[dict[str, Any]], language: str, inputs: dict[str, Any]) -> dict[str, Any]:
    sentences: list[dict[str, Any]] = []
    for fact in facts:
        if fact["kind"] in _SKIP:
            continue
        text = _sentence(fact, language)
        if text:
            sentences.append({"text": text, "facts": [fact["id"]]})
    if inputs.get("sentence_range"):
        low, high = inputs["sentence_range"]
        sentences = sentences[: max(high, 1)] or [{"text": _WARM[language][0], "facts": []}]
        return {"sentences": sentences}
    low, _ = inputs.get("word_range") or (0, 0)
    warm = iter(_WARM[language] * 4)
    while sum(len(str(s["text"]).split()) for s in sentences) < int(low):
        sentences.append({"text": next(warm), "facts": []})
    headline = sentences[0] if sentences and sentences[0]["facts"] else None
    return {"headline": headline, "sentences": sentences}


def write(task: str, prompt: str) -> dict[str, Any]:
    languages, inputs = _inputs(prompt)
    return {lang: _text(inputs["facts"], lang, inputs) for lang in languages if lang in _WARM}


def responses() -> dict[str, Callable[[str, str], dict[str, Any]]]:
    """FakeProvider responses for every writing task."""
    return {f"{task}.v1": write for task in _WRITING_TASKS}


def provider_for(settings: Settings) -> LLMProvider | None:
    """The offline writer when LLM_PROVIDER=fake; None leaves the configured provider."""
    return FakeProvider(responses=responses()) if settings.llm_provider == "fake" else None
