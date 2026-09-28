"""Import all ORM models here so Alembic autogenerate sees them."""

from app.models.ai_run import AIRun  # noqa: F401
from app.models.audit_event import AuditEvent  # noqa: F401
from app.models.auth_session import AuthSession  # noqa: F401
from app.models.base import Base  # noqa: F401
from app.models.booking import Booking  # noqa: F401
from app.models.business import Business  # noqa: F401
from app.models.business_settings import BusinessSettings  # noqa: F401
from app.models.contact import Contact  # noqa: F401
from app.models.customer import Customer  # noqa: F401
from app.models.idempotency import IdempotencyRecord  # noqa: F401
from app.models.lead import Lead, LeadActivity  # noqa: F401
from app.models.membership import BusinessMembership  # noqa: F401
from app.models.notification import Notification, NotificationPreference  # noqa: F401
from app.models.operations import (  # noqa: F401
    Approval,
    Attendance,
    DomainEvent,
    Member,
    Membership,
    MembershipPlan,
    Payment,
    Renewal,
    Seat,
    SeatAllocation,
    SeatArea,
)
from app.models.ops_vocab import (  # noqa: F401
    AI_CONVERSATION_STATUSES,
    AI_MESSAGE_ROLES,
    AI_RECOMMENDATION_STATUSES,
    AI_RISK_LEVELS,
    AI_RUN_STATUSES,
    ALLOCATION_STATUSES,
    APPROVAL_ACTIONS,
    APPROVAL_STATUSES,
    APPROVAL_TRANSITIONS,
    ATTRIBUTION_SUBJECT_TYPES,
    ATTENDANCE_SOURCES,
    AUDIT_ACTIONS,
    AUDIT_RESULTS,
    AUTOMATION_ACTION_TYPES,
    AUTOMATION_STATUSES,
    COMM_CHANNELS,
    COMM_DIRECTIONS,
    COMM_STATUSES,
    CONVERSATION_STATUSES,
    CROSS_SELL_STATUSES,
    DOMAIN_EVENTS,
    GROWTH_SOURCES_DEFAULT,
    LEAD_ROUTED_BY,
    MEMBER_STATUSES,
    MEMBERSHIP_PAYMENT_STATES,
    OPERATIONAL_MEMBERSHIP_STATUSES,
    OPERATIONAL_MEMBERSHIP_TRANSITIONS,
    PAYMENT_METHODS,
    PAYMENT_STATUSES,
    PAYMENT_TRANSITIONS,
    PLAN_CATEGORIES,
    REFERRAL_STATUSES,
    RENEWAL_STATUSES,
    RENEWAL_TRANSITIONS,
    SEAT_STATUSES,
    SEAT_TYPES,
    TASK_PRIORITIES,
    TASK_RELATED_TYPES,
    TASK_STATUSES,
    TASK_TRANSITIONS,
)
from app.models.person import IdentityLink, Person  # noqa: F401
from app.models.rbac import Permission, Role, RolePermission  # noqa: F401
from app.models.task import Task  # noqa: F401
from app.models.user import User  # noqa: F401

# Blocks 8-12: automation, communication, AI business layer, growth.
from app.models.automation import AutomationExecution, AutomationRule, DailyReport  # noqa: F401
from app.models.communication import (  # noqa: F401
    CommunicationPreference,
    Conversation,
    Message,
    MessageDeliveryEvent,
    MessageTemplate,
)
from app.models.ai_business import (  # noqa: F401
    AIConversation,
    AIMessage,
    AIRecommendation,
    AIToolCall,
)
from app.models.growth import (  # noqa: F401
    AnalyticsSnapshot,
    Attribution,
    BusinessRelationship,
    CrossSellOpportunity,
    GrowthSource,
    Referral,
)

__all__ = [
    "AIRun",
    "AIConversation",
    "AIMessage",
    "AIRecommendation",
    "AIToolCall",
    "AnalyticsSnapshot",
    "Approval",
    "Attendance",
    "Attribution",
    "AuditEvent",
    "AuthSession",
    "AutomationExecution",
    "AutomationRule",
    "Base",
    "Booking",
    "Business",
    "BusinessMembership",
    "BusinessRelationship",
    "BusinessSettings",
    "CommunicationPreference",
    "Contact",
    "Conversation",
    "CrossSellOpportunity",
    "Customer",
    "DailyReport",
    "DomainEvent",
    "GrowthSource",
    "IdempotencyRecord",
    "IdentityLink",
    "Lead",
    "LeadActivity",
    "Member",
    "Membership",
    "MembershipPlan",
    "Message",
    "MessageDeliveryEvent",
    "MessageTemplate",
    "Notification",
    "NotificationPreference",
    "Payment",
    "Person",
    "Permission",
    "Referral",
    "Renewal",
    "Role",
    "RolePermission",
    "Seat",
    "SeatAllocation",
    "SeatArea",
    "Task",
    "User",
]
