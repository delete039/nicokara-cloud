from uuid import UUID, uuid4

from fastapi import APIRouter, Request, Response, status

from app.schemas.analytics import PageviewRequest


router = APIRouter(prefix="/analytics", tags=["analytics"])

VISIT_COOKIE = "nicokara_visit"
VISIT_MAX_AGE_SECONDS = 30 * 60


def _visit_id(request: Request) -> str:
    supplied = request.cookies.get(VISIT_COOKIE, "")
    try:
        return str(UUID(supplied))
    except ValueError:
        return str(uuid4())


@router.post("/pageview", status_code=status.HTTP_204_NO_CONTENT)
def record_pageview(request: Request, payload: PageviewRequest) -> Response:
    visit_id = _visit_id(request)
    request.app.state.database.record_pageview(
        visit_id=visit_id,
        path=payload.path,
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        VISIT_COOKIE,
        visit_id,
        max_age=VISIT_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response
