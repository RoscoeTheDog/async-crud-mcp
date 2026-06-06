"""Override a staged replacement in a transaction. See ADR-001."""

from typing import Union

from async_crud_mcp.core import TransactionManager
from async_crud_mcp.models import AmendRequest, AmendResponse, ErrorCode, ErrorResponse


async def async_amend(
    request: AmendRequest,
    transaction_manager: TransactionManager,
    user_key: str,
) -> Union[AmendResponse, ErrorResponse]:
    """Hand-edit the staged replacement for one match before commit."""
    m = transaction_manager.amend(request.txn_id, user_key, request.match_id, request.replacement)
    if m is None:
        if transaction_manager.get(request.txn_id, user_key) is None:
            return ErrorResponse(error_code=ErrorCode.TXN_NOT_FOUND, message=f"Transaction not found or expired: {request.txn_id}")
        return ErrorResponse(error_code=ErrorCode.VALIDATION_ERROR, message=f"match_id {request.match_id} not found in transaction")
    return AmendResponse(txn_id=request.txn_id, match_id=request.match_id)
