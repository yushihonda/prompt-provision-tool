from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RetryLayer(str, Enum):
    TRANSPORT = "transport"
    WORKFLOW = "workflow"


class RetryReason(str, Enum):
    TRANSPORT_ERROR = "transport_error"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_TIMEOUT = "provider_timeout"
    MALFORMED_OUTPUT = "malformed_output"
    VERIFICATION_FAILED = "verification_failed"
    DEPENDENCY_NOT_READY = "dependency_not_ready"
    LOCAL_ENVIRONMENT_ERROR = "local_environment_error"
    CANCELLED_BY_USER = "cancelled_by_user"


@dataclass(slots=True)
class RetryDecision:
    should_retry: bool
    layer: RetryLayer
    reason: RetryReason
    next_delay_seconds: float


class RetryPolicy:
    """
    Two-layer retry policy.

    Transport retry is reserved for transient provider / network issues.
    Workflow retry is reserved for semantic continuation decisions such as
    verification failure and dependency ordering.
    """

    def decide(self, reason: RetryReason, attempt: int) -> RetryDecision:
        transport_reasons = {
            RetryReason.TRANSPORT_ERROR,
            RetryReason.PROVIDER_RATE_LIMIT,
            RetryReason.PROVIDER_TIMEOUT,
            RetryReason.LOCAL_ENVIRONMENT_ERROR,
        }

        workflow_reasons = {
            RetryReason.MALFORMED_OUTPUT,
            RetryReason.VERIFICATION_FAILED,
            RetryReason.DEPENDENCY_NOT_READY,
        }

        if reason == RetryReason.CANCELLED_BY_USER:
            return RetryDecision(False, RetryLayer.WORKFLOW, reason, 0.0)

        if reason in transport_reasons:
            capped_attempt = min(attempt, 5)
            return RetryDecision(
                should_retry=attempt < 5,
                layer=RetryLayer.TRANSPORT,
                reason=reason,
                next_delay_seconds=float(2**capped_attempt),
            )

        if reason in workflow_reasons:
            return RetryDecision(
                should_retry=attempt < 2,
                layer=RetryLayer.WORKFLOW,
                reason=reason,
                next_delay_seconds=1.5 * (attempt + 1),
            )

        return RetryDecision(False, RetryLayer.WORKFLOW, reason, 0.0)
