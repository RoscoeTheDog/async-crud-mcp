"""Discard a staged transaction (idempotent). See ADR-001."""

from async_crud_mcp.core import TransactionManager
from async_crud_mcp.models import AbortRequest, AbortResponse


async def async_abort(
    request: AbortRequest,
    transaction_manager: TransactionManager,
    user_key: str,
) -> AbortResponse:
    """Discard a staged transaction; only removes one owned by this user_key."""
    discarded = False
    if transaction_manager.get(request.txn_id, user_key) is not None:
        discarded = transaction_manager.remove(request.txn_id)
    return AbortResponse(txn_id=request.txn_id, discarded=discarded)
