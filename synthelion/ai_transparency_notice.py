# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Produces a user-facing disclosure message informing the end user that they are
interacting with an AI system and that their input is screened/masked for sensitive
data before being sent to the model. Supports (but does not by itself guarantee)
the transparency obligations of EU AI Act Art.50 for limited-risk AI systems —
whether it applies, and the exact required wording, depends on your use case and
should be confirmed with legal counsel. This only provides a configurable,
ready-to-display message.
"""
from __future__ import annotations

_DEFAULT_MESSAGES: dict[str, str] = {
    "en": "You are interacting with an AI system. Your messages are screened locally and any personal or sensitive data is masked before being sent to the AI model (EU AI Act Art.50 transparency notice).",
    "it": "Stai interagendo con un sistema di intelligenza artificiale. I tuoi messaggi vengono analizzati localmente e i dati personali o sensibili vengono mascherati prima dell'invio al modello AI (informativa ai sensi dell'Art.50 dell'AI Act).",
    "de": "Sie interagieren mit einem KI-System. Ihre Nachrichten werden lokal geprüft und personenbezogene oder sensible Daten werden vor der Übermittlung an das KI-Modell maskiert (Transparenzhinweis gemäß Art. 50 KI-Verordnung).",
    "fr": "Vous interagissez avec un système d'IA. Vos messages sont analysés localement et toute donnée personnelle ou sensible est masquée avant l'envoi au modèle d'IA (mention de transparence conformément à l'art. 50 du règlement IA).",
    "es": "Está interactuando con un sistema de IA. Sus mensajes se analizan localmente y los datos personales o sensibles se enmascaran antes de enviarlos al modelo de IA (aviso de transparencia conforme al art. 50 del Reglamento de IA).",
}


def register_message(language: str, message: str) -> None:
    """Registers or overrides the built-in message for a given language code."""
    _DEFAULT_MESSAGES[language.lower()] = message


def get_transparency_notice(language: str = "en", custom_message: str | None = None) -> str:
    """Returns the disclosure message for *language*, or *custom_message* verbatim
    when given. Falls back to English for an unknown language code."""
    if custom_message:
        return custom_message
    return _DEFAULT_MESSAGES.get((language or "en").lower(), _DEFAULT_MESSAGES["en"])
