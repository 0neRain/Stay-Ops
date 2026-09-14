from dataclasses import dataclass

from app.models.enums import EscalationUrgency


@dataclass(frozen=True)
class RiskExample:
    key: str
    category: str
    urgency: EscalationUrgency
    text: str


RISK_EXAMPLES: tuple[RiskExample, ...] = (
    RiskExample("refund-01", "refund", EscalationUrgency.HIGH, "I want my money back."),
    RiskExample("refund-02", "refund", EscalationUrgency.HIGH, "Can you reimburse my stay?"),
    RiskExample("refund-03", "refund", EscalationUrgency.HIGH, "Please reverse the charge."),
    RiskExample("refund-04", "refund", EscalationUrgency.HIGH, "I need compensation."),
    RiskExample(
        "cancellation-01",
        "cancellation",
        EscalationUrgency.HIGH,
        "I need to cancel my booking.",
    ),
    RiskExample(
        "cancellation-02",
        "cancellation",
        EscalationUrgency.HIGH,
        "Please call off my reservation.",
    ),
    RiskExample(
        "cancellation-03",
        "cancellation",
        EscalationUrgency.HIGH,
        "I no longer want to stay here.",
    ),
    RiskExample(
        "payment-01",
        "payment",
        EscalationUrgency.HIGH,
        "My card was charged twice.",
    ),
    RiskExample(
        "payment-02",
        "payment",
        EscalationUrgency.HIGH,
        "There is an incorrect amount on my bill.",
    ),
    RiskExample(
        "payment-03",
        "payment",
        EscalationUrgency.HIGH,
        "Can I pay using a different credit card?",
    ),
    RiskExample(
        "access-01",
        "access",
        EscalationUrgency.HIGH,
        "I am locked outside the property.",
    ),
    RiskExample(
        "access-02",
        "access",
        EscalationUrgency.HIGH,
        "The keypad PIN does not work.",
    ),
    RiskExample(
        "access-03",
        "access",
        EscalationUrgency.HIGH,
        "Send me the current door code.",
    ),
    RiskExample(
        "access-04",
        "access",
        EscalationUrgency.HIGH,
        "How can I get the keys to the apartment?",
    ),
    RiskExample(
        "access-05",
        "access",
        EscalationUrgency.HIGH,
        "I cannot enter the house.",
    ),
    RiskExample("safety-01", "safety", EscalationUrgency.EMERGENCY, "There is a fire."),
    RiskExample(
        "safety-02",
        "safety",
        EscalationUrgency.EMERGENCY,
        "I smell gas inside the property.",
    ),
    RiskExample(
        "safety-03",
        "safety",
        EscalationUrgency.EMERGENCY,
        "The carbon monoxide alarm is sounding.",
    ),
    RiskExample(
        "safety-04",
        "safety",
        EscalationUrgency.EMERGENCY,
        "Someone has been injured.",
    ),
    RiskExample(
        "safety-05",
        "safety",
        EscalationUrgency.EMERGENCY,
        "An unknown person broke into the apartment.",
    ),
    RiskExample(
        "safety-06",
        "safety",
        EscalationUrgency.EMERGENCY,
        "There is smoke coming from the kitchen.",
    ),
)
