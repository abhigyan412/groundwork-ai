"""Admin API. Every route depends on `CurrentOrg` (JWT only); never on org_id from the request."""

from fastapi import APIRouter

from app.auth.deps import CurrentOrg
from app.auth.schemas import MeResponse, OrgOut

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/me", responses={401: {"description": "Missing or invalid admin token"}})
async def me(account: CurrentOrg) -> MeResponse:
    return MeResponse(org=OrgOut(id=account.org_id, name=account.org_name), email=account.email)
