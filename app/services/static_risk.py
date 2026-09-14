import re
import unicodedata
from dataclasses import dataclass

from app.models.enums import EscalationUrgency


@dataclass(frozen=True)
class StaticRiskAssessment:
    rule_id: str
    category: str
    urgency: EscalationUrgency
    evidence: tuple[str, ...]


_EMERGENCY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("safety.carbon-monoxide", ("carbon monoxide",)),
    ("safety.gas", ("gas leak", "smell gas", "smells like gas")),
    ("safety.fire", ("fire", "smoke")),
    ("safety.medical", ("medical emergency", "injured", "has been hurt")),
    ("safety.intrusion", ("break in", "broke in", "someone is inside")),
)
_HIGH_RISK_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("financial.refund", "refund", ("refund", "reimburse", "money back", "compensation")),
    (
        "reservation.cancellation",
        "cancellation",
        ("cancel my", "cancel our", "cancellation", "call off my", "call off our"),
    ),
    (
        "financial.payment",
        "payment",
        ("charged twice", "duplicate charge", "incorrect charge", "payment", "credit card"),
    ),
)
_ACCESS_OBJECTS = (
    "access code",
    "door code",
    "entry code",
    "key",
    "keys",
    "keypad",
    "lock",
    "pin",
)
_ACCESS_FAILURES = (
    "cannot enter",
    "cannot get in",
    "does not work",
    "failed",
    "fails",
    "is not working",
    "lost",
    "missing",
    "not working",
    "rejecting",
    "rejected",
    "unable to enter",
    "will not open",
)
_ACCESS_DISCLOSURES = (
    "current",
    "give me",
    "send me",
    "share",
    "tell me",
    "what is",
)
_DIRECT_ACCESS_FAILURES = (
    "cannot enter",
    "cannot get in",
    "locked out",
    "locked outside",
    "unable to enter",
)


def normalize_for_policy(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("’", "'").replace("-", " ")
    normalized = normalized.replace("can't", "cannot").replace("won't", "will not")
    normalized = normalized.replace("doesn't", "does not")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", normalized)).strip()


def _matched_phrases(value: str, phrases: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(phrase for phrase in phrases if re.search(rf"\b{re.escape(phrase)}\b", value))


def assess_static_risk(query: str) -> StaticRiskAssessment | None:
    normalized = normalize_for_policy(query)

    for rule_id, phrases in _EMERGENCY_RULES:
        evidence = _matched_phrases(normalized, phrases)
        if evidence:
            return StaticRiskAssessment(
                rule_id=rule_id,
                category="safety",
                urgency=EscalationUrgency.EMERGENCY,
                evidence=evidence,
            )

    for rule_id, category, phrases in _HIGH_RISK_RULES:
        evidence = _matched_phrases(normalized, phrases)
        if evidence:
            return StaticRiskAssessment(
                rule_id=rule_id,
                category=category,
                urgency=EscalationUrgency.HIGH,
                evidence=evidence,
            )

    direct_failure = _matched_phrases(normalized, _DIRECT_ACCESS_FAILURES)
    access_objects = _matched_phrases(normalized, _ACCESS_OBJECTS)
    access_intents = _matched_phrases(
        normalized,
        _ACCESS_FAILURES + _ACCESS_DISCLOSURES,
    )
    if direct_failure or (access_objects and access_intents):
        return StaticRiskAssessment(
            rule_id="property.access",
            category="access",
            urgency=EscalationUrgency.HIGH,
            evidence=direct_failure + access_objects + access_intents,
        )
    return None
