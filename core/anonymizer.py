"""Structural anonymization for data and free-form evidence sent to AI."""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any


REDACTED_VALUE = "***"

_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "senha",
    "pwd",
    "secret",
    "token",
    "apikey",
    "api_key",
    "community",
    "credential",
    "psk",
)

# The dot-aware boundaries are important: without them, the first four arcs of
# an SNMP OID such as 1.3.6.1.4.1 would be mistaken for an IPv4 address.  The
# final dot is accepted only when it is punctuation, not another numeric arc.
_IPV4_CANDIDATE = re.compile(
    r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)"
)
_IPV6_CANDIDATE = re.compile(
    r"(?<![0-9A-Fa-f:.])"
    r"(?:(?:[0-9A-Fa-f]{0,4}:){2,7}"
    r"(?:[0-9A-Fa-f]{0,4}|(?:\d{1,3}\.){3}\d{1,3}))"
    r"(?![0-9A-Fa-f:]|\.[0-9A-Fa-f:])"
)

_SENSITIVE_NAME = rf"[\w.-]*(?:{'|'.join(map(re.escape, _SENSITIVE_KEY_PARTS))})[\w.-]*"
_QUOTED_SECRET = re.compile(
    rf"(?P<prefix>(?P<keyquote>[\"'])(?P<key>{_SENSITIVE_NAME})(?P=keyquote)\s*:\s*)"
    r"(?P<valuequote>[\"'])(?P<value>(?:\\.|(?!(?P=valuequote))[\s\S])*)(?P=valuequote)",
    re.IGNORECASE,
)
_LABELED_SECRET = re.compile(
    rf"(?P<prefix>\b(?P<key>{_SENSITIVE_NAME})\b\s*[:=]\s*)"
    r"(?:(?P<quote>[\"'])(?P<quoted>(?:\\.|(?!(?P=quote))[\s\S])*)(?P=quote)|(?P<bare>[^\s,;}\]]+))",
    re.IGNORECASE,
)
_JSON_SECRET_FIELD = re.compile(
    rf'(?P<prefix>"(?P<key>{_SENSITIVE_NAME})"\s*:\s*)',
    re.IGNORECASE,
)
_OID_VALUE_CONTEXT = re.compile(
    r"(?:^|[\s,{;])[\"']?(?:snmp[_ -]?oid|oid)[\"']?\s*[:=]\s*[\"']?$",
    re.IGNORECASE,
)
_OID_VALUE = re.compile(r"\s*\d+(?:\.\d+)+\s*")


def _is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _is_oid_key(key: object) -> bool:
    return isinstance(key, str) and key.casefold() in {"oid", "snmp_oid"}


class Anonymizer:
    """Anonymize one audit while keeping repeated IP pseudonyms stable."""

    def __init__(self) -> None:
        self._ip_pseudonyms: dict[str, str] = {}
        self._next_ip_number = {4: 1, 6: 1}

    def anonymize(self, value: Any) -> Any:
        """Recursively redact sensitive fields and pseudonymize IP addresses."""
        if isinstance(value, dict):
            anonymized = {}
            for key, child in value.items():
                safe_key = self.redact_text(key) if isinstance(key, str) else key
                if _is_sensitive_key(key):
                    anonymized[safe_key] = REDACTED_VALUE
                elif _is_oid_key(key) and isinstance(child, str):
                    anonymized[safe_key] = self.redact_text(child, preserve_oid_value=True)
                else:
                    anonymized[safe_key] = self.anonymize(child)
            return anonymized
        if isinstance(value, list):
            return [self.anonymize(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.anonymize(item) for item in value)
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    def redact_text(self, text: str, *, preserve_oid_value: bool = False) -> str:
        """Redact labeled secrets and valid IP addresses in free-form text."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        redacted = self._redact_json_secret_values(text)
        redacted = _QUOTED_SECRET.sub(self._replace_quoted_secret, redacted)
        redacted = _LABELED_SECRET.sub(self._replace_labeled_secret, redacted)
        if preserve_oid_value and _OID_VALUE.fullmatch(redacted):
            return redacted
        # Try IPv6 first because an IPv4 address may be the tail of a valid
        # IPv4-mapped IPv6 address.
        redacted = self._replace_ip_candidates(redacted, _IPV6_CANDIDATE)
        return self._replace_ip_candidates(redacted, _IPV4_CANDIDATE)

    @staticmethod
    def _redact_json_secret_values(text: str) -> str:
        """Replace full JSON values for sensitive fields without breaking JSON.

        Regex alone cannot safely consume nested objects, arrays, or escaped
        string delimiters.  ``raw_decode`` identifies one complete JSON value
        while preserving all surrounding evidence verbatim.
        """
        decoder = json.JSONDecoder()
        parts = []
        cursor = 0
        for match in _JSON_SECRET_FIELD.finditer(text):
            if match.start() < cursor:
                continue
            value_start = match.end()
            try:
                _, value_end = decoder.raw_decode(text, value_start)
            except json.JSONDecodeError:
                continue
            parts.append(text[cursor:value_start])
            parts.append(json.dumps(REDACTED_VALUE))
            cursor = value_end
        if not parts:
            return text
        parts.append(text[cursor:])
        return "".join(parts)

    @staticmethod
    def _replace_quoted_secret(match: re.Match[str]) -> str:
        quote = match.group("valuequote")
        return f"{match.group('prefix')}{quote}{REDACTED_VALUE}{quote}"

    @staticmethod
    def _replace_labeled_secret(match: re.Match[str]) -> str:
        quote = match.group("quote") or ""
        return f"{match.group('prefix')}{quote}{REDACTED_VALUE}{quote}"

    def _replace_ip_candidates(self, text: str, pattern: re.Pattern[str]) -> str:
        return pattern.sub(
            lambda match: self._replace_ip_candidate(match, text),
            text,
        )

    def _replace_ip_candidate(self, match: re.Match[str], text: str) -> str:
        candidate = match.group(0)
        # A four-arc OID is ambiguous with IPv4.  Preserve it when its syntax
        # explicitly identifies it as an OID (including a JSON object key).
        if _OID_VALUE_CONTEXT.search(text[max(0, match.start() - 80):match.start()]):
            return candidate
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            return candidate

        canonical = str(address)
        pseudonym = self._ip_pseudonyms.get(canonical)
        if pseudonym is None:
            version = address.version
            pseudonym = f"<IPv{version}-{self._next_ip_number[version]}>"
            self._next_ip_number[version] += 1
            self._ip_pseudonyms[canonical] = pseudonym
        return pseudonym


def anonymize_data(value: Any) -> Any:
    """Convenience entry point for a single structural anonymization pass."""
    return Anonymizer().anonymize(value)


def redact_text(text: str) -> str:
    """Convenience entry point for a single free-form text redaction pass."""
    return Anonymizer().redact_text(text)
