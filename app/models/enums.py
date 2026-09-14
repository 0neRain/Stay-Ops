from enum import Enum


class MembershipRole(str, Enum):
    OWNER = "owner"
    MANAGER = "manager"
    SUPPORT = "support"
    VIEWER = "viewer"


class IntegrationProvider(str, Enum):
    HOSTAWAY = "hostaway"
    GUESTY = "guesty"
    DEMO = "demo"


class IntegrationStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


class ReservationStatus(str, Enum):
    INQUIRY = "inquiry"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ConversationStatus(str, Enum):
    OPEN = "open"
    PROCESSING = "processing"
    NEEDS_HUMAN = "needs_human"
    HUMAN_ACTIVE = "human_active"
    RESOLVED = "resolved"


class MessageSender(str, Enum):
    GUEST = "guest"
    AGENT = "agent"
    HUMAN = "human"
    SYSTEM = "system"


class DeliveryStatus(str, Enum):
    RECEIVED = "received"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class EscalationStatus(str, Enum):
    OPEN = "open"
    ASSIGNED = "assigned"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EscalationUrgency(str, Enum):
    NORMAL = "normal"
    HIGH = "high"
    EMERGENCY = "emergency"


class KnowledgeStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolRunStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class FeedbackRating(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
