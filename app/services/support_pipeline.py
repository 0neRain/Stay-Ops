from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    AuditEvent,
    Conversation,
    Escalation,
    Message,
    Property,
    ToolRun,
)
from app.models.enums import (
    ConversationStatus,
    DeliveryStatus,
    EscalationStatus,
    EscalationUrgency,
    MessageSender,
    ToolRunStatus,
)
from app.services.embeddings import EmbeddingProvider
from app.services.knowledge import KnowledgeHit, KnowledgeRetrievalError, KnowledgeRetriever
from app.services.risk_validation import (
    RiskValidationError,
    SemanticRiskAssessment,
    SemanticRiskValidator,
)
from app.services.static_risk import StaticRiskAssessment, assess_static_risk

PipelineAction = Literal["answered", "handoff"]


class RiskValidator(Protocol):
    async def assess(self, query: str) -> SemanticRiskAssessment: ...


class SupportState(TypedDict, total=False):
    tenant_id: UUID
    property_id: UUID
    query: str
    retrieval_hits: list[KnowledgeHit]
    retrieval_error: str | None
    retrieval_attempted: bool
    static_risk: StaticRiskAssessment | None
    semantic_risk: SemanticRiskAssessment | None
    semantic_validation_error: str | None
    semantic_assessment_attempted: bool
    action: PipelineAction
    answer: str | None
    reason: str | None
    urgency: EscalationUrgency | None
    summary: str | None
    proposed_reply: str | None


@dataclass(frozen=True)
class PipelineDecision:
    action: PipelineAction
    answer: str | None
    reason: str | None
    urgency: EscalationUrgency | None
    summary: str | None
    proposed_reply: str | None
    hits: list[KnowledgeHit]
    retrieval_error: str | None
    semantic_risk: SemanticRiskAssessment | None = None
    semantic_validation_error: str | None = None
    static_risk: StaticRiskAssessment | None = None
    retrieval_attempted: bool = False
    semantic_assessment_attempted: bool = False


@dataclass(frozen=True)
class ProcessedMessage:
    conversation: Conversation
    guest_message: Message
    decision: PipelineDecision
    response_message: Message | None
    escalation: Escalation | None


class SupportPipelineError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class SupportPipeline:
    def __init__(
        self,
        retriever: KnowledgeRetriever,
        *,
        minimum_retrieval_score: float = 0.35,
        retrieval_limit: int = 4,
        risk_validator: RiskValidator | None = None,
    ) -> None:
        self.retriever = retriever
        self.minimum_retrieval_score = minimum_retrieval_score
        self.retrieval_limit = retrieval_limit
        self.risk_validator = risk_validator

        builder = StateGraph(SupportState)
        builder.add_node("static_assess", self._static_assess)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("semantic_assess", self._semantic_assess)
        builder.add_node("assess", self._assess)
        builder.add_node("answer", self._answer)
        builder.add_node("handoff", self._handoff)
        builder.add_edge(START, "static_assess")
        builder.add_conditional_edges(
            "static_assess",
            self._route_after_static,
            {"continue": "retrieve", "handoff": "handoff"},
        )
        builder.add_edge("retrieve", "semantic_assess")
        builder.add_edge("semantic_assess", "assess")
        builder.add_conditional_edges(
            "assess",
            self._route,
            {"answer": "answer", "handoff": "handoff"},
        )
        builder.add_edge("answer", END)
        builder.add_edge("handoff", END)
        self.graph = builder.compile()

    @staticmethod
    async def _static_assess(state: SupportState) -> SupportState:
        static_risk = assess_static_risk(state["query"])
        if static_risk is None:
            return {"static_risk": None}
        return {
            "action": "handoff",
            "reason": f"Static risk rule: {static_risk.category}",
            "urgency": static_risk.urgency,
            "static_risk": static_risk,
        }

    @staticmethod
    def _route_after_static(state: SupportState) -> Literal["continue", "handoff"]:
        return "handoff" if state.get("static_risk") is not None else "continue"

    async def _retrieve(self, state: SupportState) -> SupportState:
        try:
            hits = await self.retriever.search(
                tenant_id=state["tenant_id"],
                property_id=state["property_id"],
                query=state["query"],
                limit=self.retrieval_limit,
            )
        except KnowledgeRetrievalError as exc:
            return {
                "retrieval_hits": [],
                "retrieval_error": str(exc),
                "retrieval_attempted": True,
            }
        return {
            "retrieval_hits": hits,
            "retrieval_error": None,
            "retrieval_attempted": True,
        }

    async def _semantic_assess(self, state: SupportState) -> SupportState:
        if state.get("retrieval_error") or self.risk_validator is None:
            return {
                "semantic_risk": None,
                "semantic_validation_error": None,
                "semantic_assessment_attempted": False,
            }
        try:
            semantic_risk = await self.risk_validator.assess(state["query"])
        except RiskValidationError as exc:
            return {
                "semantic_risk": None,
                "semantic_validation_error": str(exc),
                "semantic_assessment_attempted": True,
            }
        return {
            "semantic_risk": semantic_risk,
            "semantic_validation_error": None,
            "semantic_assessment_attempted": True,
        }

    async def _assess(self, state: SupportState) -> SupportState:
        if state.get("retrieval_error"):
            return {
                "action": "handoff",
                "reason": "Knowledge retrieval failed",
                "urgency": EscalationUrgency.NORMAL,
            }

        if state.get("semantic_validation_error"):
            return {
                "action": "handoff",
                "reason": "Semantic risk validation failed",
                "urgency": EscalationUrgency.NORMAL,
            }
        semantic_risk = state.get("semantic_risk")
        if semantic_risk is not None and semantic_risk.requires_handoff:
            return {
                "action": "handoff",
                "reason": f"Semantic risk match: {semantic_risk.category}",
                "urgency": semantic_risk.urgency,
            }

        hits = state.get("retrieval_hits", [])
        if not hits or hits[0].score < self.minimum_retrieval_score:
            return {
                "action": "handoff",
                "reason": "No sufficiently relevant published knowledge was found",
                "urgency": EscalationUrgency.NORMAL,
                "semantic_risk": semantic_risk,
            }
        if hits[0].metadata.get("requires_human_review") is True:
            return {
                "action": "handoff",
                "reason": "Relevant knowledge requires human review",
                "urgency": EscalationUrgency.NORMAL,
                "semantic_risk": semantic_risk,
            }
        return {"action": "answered", "semantic_risk": semantic_risk}

    @staticmethod
    def _route(state: SupportState) -> Literal["answer", "handoff"]:
        return "answer" if state["action"] == "answered" else "handoff"

    @staticmethod
    async def _answer(state: SupportState) -> SupportState:
        best_hit = state["retrieval_hits"][0]
        return {
            "answer": best_hit.content,
            "reason": None,
            "urgency": None,
            "summary": None,
            "proposed_reply": None,
        }

    @staticmethod
    async def _handoff(state: SupportState) -> SupportState:
        reason = state["reason"]
        query = state["query"].strip()
        return {
            "answer": None,
            "summary": f'Guest asks: "{query}" Handoff reason: {reason}.',
            "proposed_reply": (
                "Thanks for letting us know. A member of the property team is reviewing "
                "this now and will follow up shortly."
            ),
        }

    async def run(self, *, tenant_id: UUID, property_id: UUID, query: str) -> PipelineDecision:
        result = await self.graph.ainvoke(
            {"tenant_id": tenant_id, "property_id": property_id, "query": query}
        )
        return PipelineDecision(
            action=result["action"],
            answer=result.get("answer"),
            reason=result.get("reason"),
            urgency=result.get("urgency"),
            summary=result.get("summary"),
            proposed_reply=result.get("proposed_reply"),
            hits=result.get("retrieval_hits", []),
            retrieval_error=result.get("retrieval_error"),
            semantic_risk=result.get("semantic_risk"),
            semantic_validation_error=result.get("semantic_validation_error"),
            static_risk=result.get("static_risk"),
            retrieval_attempted=result.get("retrieval_attempted", False),
            semantic_assessment_attempted=result.get("semantic_assessment_attempted", False),
        )


async def _load_conversation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    property_id: UUID,
    conversation_id: UUID | None,
) -> Conversation:
    property_record = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.tenant_id == tenant_id,
            Property.is_active.is_(True),
        )
    )
    if property_record is None:
        raise SupportPipelineError(404, "Property not found")

    if conversation_id is None:
        conversation = Conversation(
            tenant_id=tenant_id,
            property_id=property_id,
            status=ConversationStatus.OPEN,
        )
        session.add(conversation)
        await session.flush()
        return conversation

    existing_conversation = await session.scalar(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.property_id == property_id,
        )
        .with_for_update()
    )
    if existing_conversation is None:
        raise SupportPipelineError(404, "Conversation not found")
    if existing_conversation.status == ConversationStatus.RESOLVED:
        raise SupportPipelineError(409, "Conversation is already resolved")
    return existing_conversation


async def _open_or_create_escalation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    decision: PipelineDecision,
) -> Escalation:
    escalation = await session.scalar(
        select(Escalation)
        .where(
            Escalation.tenant_id == tenant_id,
            Escalation.conversation_id == conversation.id,
            Escalation.status.in_([EscalationStatus.OPEN, EscalationStatus.ASSIGNED]),
        )
        .order_by(Escalation.created_at.desc())
        .limit(1)
    )
    if escalation is None:
        escalation = Escalation(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            reason=decision.reason or "Human review required",
            summary=decision.summary,
            proposed_reply=decision.proposed_reply,
            urgency=decision.urgency or EscalationUrgency.NORMAL,
        )
        session.add(escalation)
        await session.flush()
    return escalation


async def process_guest_message(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    property_id: UUID,
    content: str,
    conversation_id: UUID | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    semantic_risk_threshold: float = 0.80,
) -> ProcessedMessage:
    conversation = await _load_conversation(
        session,
        tenant_id=tenant_id,
        property_id=property_id,
        conversation_id=conversation_id,
    )
    now = datetime.now(timezone.utc)
    guest_message = Message(
        conversation_id=conversation.id,
        sender=MessageSender.GUEST,
        content=content.strip(),
        delivery_status=DeliveryStatus.RECEIVED,
    )
    session.add(guest_message)
    conversation.last_message_at = now
    await session.flush()

    if conversation.status in {
        ConversationStatus.NEEDS_HUMAN,
        ConversationStatus.HUMAN_ACTIVE,
    }:
        decision = PipelineDecision(
            action="handoff",
            answer=None,
            reason="Conversation is already owned by human support",
            urgency=EscalationUrgency.NORMAL,
            summary=f'Guest sent a follow-up: "{content.strip()}".',
            proposed_reply=None,
            hits=[],
            retrieval_error=None,
        )
    else:
        conversation.status = ConversationStatus.PROCESSING
        risk_validator = (
            SemanticRiskValidator(
                session,
                embedding_provider=embedding_provider,
                threshold=semantic_risk_threshold,
            )
            if embedding_provider is not None
            else None
        )
        pipeline = SupportPipeline(
            KnowledgeRetriever(session, embedding_provider=embedding_provider),
            risk_validator=risk_validator,
        )
        decision = await pipeline.run(
            tenant_id=tenant_id,
            property_id=property_id,
            query=content,
        )

    static_risk = decision.static_risk
    if static_risk is not None:
        session.add(
            ToolRun(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                message_id=guest_message.id,
                tool_name="policy.static_risk",
                input_json={"query": content},
                output_json={
                    "rule_id": static_risk.rule_id,
                    "category": static_risk.category,
                    "urgency": static_risk.urgency.value,
                    "evidence": list(static_risk.evidence),
                    "requires_handoff": True,
                },
                status=ToolRunStatus.SUCCESS,
            )
        )
    if decision.retrieval_attempted:
        session.add(
            ToolRun(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                message_id=guest_message.id,
                tool_name="knowledge.retrieve",
                input_json={"query": content, "property_id": str(property_id)},
                output_json=(
                    {
                        "hits": [
                            {"chunk_id": str(hit.chunk_id), "score": hit.score}
                            for hit in decision.hits
                        ]
                    }
                    if decision.retrieval_error is None
                    else None
                ),
                status=(
                    ToolRunStatus.FAILED
                    if decision.retrieval_error is not None
                    else ToolRunStatus.SUCCESS
                ),
                error_type="embedding_provider" if decision.retrieval_error else None,
                error_message=decision.retrieval_error,
            )
        )
    if decision.semantic_assessment_attempted:
        semantic_risk = decision.semantic_risk
        session.add(
            ToolRun(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                message_id=guest_message.id,
                tool_name="policy.semantic_risk",
                input_json={"query": content},
                output_json=(
                    {
                        "policy_key": semantic_risk.policy_key,
                        "category": semantic_risk.category,
                        "urgency": semantic_risk.urgency.value,
                        "score": semantic_risk.score,
                        "threshold": semantic_risk.threshold,
                        "requires_handoff": semantic_risk.requires_handoff,
                    }
                    if semantic_risk is not None
                    else None
                ),
                status=(
                    ToolRunStatus.FAILED
                    if decision.semantic_validation_error is not None
                    else ToolRunStatus.SUCCESS
                ),
                error_type=(
                    "semantic_risk_validation"
                    if decision.semantic_validation_error is not None
                    else None
                ),
                error_message=decision.semantic_validation_error,
            )
        )

    response_message: Message | None = None
    escalation: Escalation | None = None
    if decision.action == "answered":
        citations = [
            {
                "chunk_id": str(hit.chunk_id),
                "document_id": str(hit.document_id),
                "version_id": str(hit.version_id),
                "title": hit.title,
                "score": hit.score,
            }
            for hit in decision.hits
        ]
        response_message = Message(
            conversation_id=conversation.id,
            sender=MessageSender.AGENT,
            content=decision.answer or "",
            source_citations=citations,
            delivery_status=DeliveryStatus.SENT,
        )
        session.add(response_message)
        conversation.status = ConversationStatus.OPEN
        conversation.last_message_at = now
    else:
        escalation = await _open_or_create_escalation(
            session,
            tenant_id=tenant_id,
            conversation=conversation,
            decision=decision,
        )
        conversation.status = ConversationStatus.NEEDS_HUMAN

    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            event_type=f"support.{decision.action}",
            entity_type="conversation",
            entity_id=conversation.id,
            details={
                "guest_message_id": str(guest_message.id),
                "escalation_id": str(escalation.id) if escalation else None,
                "reason": decision.reason,
            },
            created_at=now,
        )
    )
    await session.commit()
    return ProcessedMessage(
        conversation=conversation,
        guest_message=guest_message,
        decision=decision,
        response_message=response_message,
        escalation=escalation,
    )
