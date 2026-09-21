"""Enterprise middleware — auth gate + quota enforcement.

Used by the proxy (HTTP requests) and the dashboard (per-user filtering).
Provides the ``EnterpriseAuthResult`` dataclass with all information
needed to either forward or block a request.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from . import users as _users
from . import subscriptions as _subs
from . import provider_keys as _pk
from . import activity as _act
from .cost_sync import estimate_cost

log = logging.getLogger(__name__)


@dataclass
class EnterpriseAuthResult:
    """Result of the enterprise auth + quota check."""
    allowed: bool
    user: dict[str, Any] | None = None
    provider_key: dict[str, Any] | None = None
    subscription: dict[str, Any] | None = None
    real_api_key: str | None = None
    error_code: str | None = None       # "missing_token" | "invalid_token" | "user_disabled" | "no_subscription" | "quota_exceeded" | "no_provider_assigned"
    error_message: str | None = None
    http_status: int = 401


def check_enterprise_auth(
    virtual_token: str | None,
    provider: str | None = None,
    model: str | None = None,
) -> EnterpriseAuthResult:
    """Full enterprise auth + quota check.

    1. Validate virtual_token → user lookup
    2. Check user enabled
    3. Find provider key assigned to user
    4. Find active subscription
    5. Check quota
    6. Return real API key for injection
    """
    if not virtual_token:
        return EnterpriseAuthResult(
            allowed=False,
            error_code="missing_token",
            error_message="Authorization header missing or empty",
            http_status=401,
        )

    user = _users.get_user_by_token(virtual_token)
    if not user:
        return EnterpriseAuthResult(
            allowed=False,
            error_code="invalid_token",
            error_message="Unknown virtual token",
            http_status=401,
        )

    if user["status"] != "active":
        return EnterpriseAuthResult(
            allowed=False,
            user=user,
            error_code="user_disabled",
            error_message=f"User {user['label']} is disabled",
            http_status=403,
        )

    if not provider:
        return EnterpriseAuthResult(
            allowed=False,
            user=user,
            error_code="missing_provider",
            error_message="Could not determine provider from request",
            http_status=400,
        )

    # Find provider key assigned to this user
    pk = _pk.find_key_for_user(user["user_id"], provider)
    if not pk:
        return EnterpriseAuthResult(
            allowed=False,
            user=user,
            error_code="no_provider_assigned",
            error_message=f"No {provider} provider assigned to this user",
            http_status=403,
        )

    # Find active subscription
    sub = _subs.find_active_sub(user["user_id"], provider, model)
    if not sub:
        return EnterpriseAuthResult(
            allowed=False,
            user=user,
            provider_key=pk,
            error_code="no_subscription",
            error_message=f"No active subscription for {provider}",
            http_status=403,
        )

    # Check quota
    if not _subs.quota_check(sub):
        msg = "Token quota exhausted" if sub["type"] == "consumo" else "Monthly cost limit reached"
        return EnterpriseAuthResult(
            allowed=False,
            user=user,
            provider_key=pk,
            subscription=sub,
            error_code="quota_exceeded",
            error_message=msg,
            http_status=429,
        )

    # Decrypt real key
    real_key = _pk.get_real_key(pk["id"])

    return EnterpriseAuthResult(
        allowed=True,
        user=user,
        provider_key=pk,
        subscription=sub,
        real_api_key=real_key,
    )


def record_proxy_usage(
    user: dict[str, Any],
    provider: str,
    model: str | None,
    path: str,
    status_code: int,
    tokens_before: int,
    tokens_after: int,
    duration_ms: float,
    compressed: bool,
    real_input_tokens: int | None = None,
    real_output_tokens: int | None = None,
    blocked: bool = False,
    block_reason: str | None = None,
) -> None:
    """Log activity + update subscription counters after a proxy request.

    Prefers the upstream provider's own reported usage (`real_input_tokens`/
    `real_output_tokens`, parsed from the response body — see
    `proxy.py::_extract_usage`) over any local estimate: that's the number
    the provider actually bills, and it's the only source for output/
    completion tokens at all, since Synthelion never sees the model's output
    before the response comes back. Falls back to `tokens_after` (the tokens
    actually sent upstream, post-compression) with 0 assumed output tokens
    only when real usage isn't available (streaming responses, or a provider
    that doesn't report `usage`) — better to undercount than to charge a
    subscription for tokens compression *saved* and never sent anywhere.
    """
    if real_input_tokens is not None or real_output_tokens is not None:
        input_tokens = real_input_tokens or 0
        output_tokens = real_output_tokens or 0
    else:
        input_tokens = tokens_after
        output_tokens = 0
    tokens_used = input_tokens + output_tokens
    cost = estimate_cost(provider, model or "", input_tokens, output_tokens)

    _act.log_request(
        user_id=user["user_id"],
        provider=provider,
        model=model,
        path=path,
        status_code=status_code,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        tokens_used=tokens_used,
        cost_usd=cost,
        duration_ms=duration_ms,
        compressed=compressed,
        blocked=blocked,
        block_reason=block_reason,
    )

    # Update subscription usage
    sub = _subs.find_active_sub(user["user_id"], provider, model)
    if sub:
        _subs.record_usage(sub["id"], tokens_used, cost)
