"""HTTP routes. Thin: validation and status codes here, the workflow in app/cases.py."""

import tempfile
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status

from app.api_models import CaseView, ConfirmRequest, LetterView, LookupRequest, SampleView
from app.cases import CaseService, NotFound, NotReady
from app.config import ConfigError
from app.extract import ExtractionError, NotABillError
from app.refdb import open_reference
from app.settings import Settings
from app.store import Store
from app.uploads import SUFFIX_KINDS

router = APIRouter(prefix="/api")
CHUNK = 64 * 1024


class RateLimiter:
    """Case creations per client per hour, kept in memory. Each case can spend model credit."""

    def __init__(self, limit: int) -> None:
        self.limit, self._hits, self._lock = limit, defaultdict(deque), Lock()

    def check(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] > 3600:
                hits.popleft()
            if len(hits) >= self.limit:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many cases this hour. Try again later.")
            hits.append(now)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[CaseService]:
    store, ref = Store(settings.state_db), open_reference(settings.reference_db)
    try:
        yield CaseService(settings, store, ref)
    finally:
        store.close()
        ref.close()


Service = Annotated[CaseService, Depends(get_service)]


def limit_lookups(request: Request) -> None:
    """Each lookup spends Tavily and model credit, and the demo toggle lets a visitor choose the name."""
    request.app.state.lookup_limiter.check(request.client.host if request.client else "unknown")


def limit_creations(request: Request) -> None:
    request.app.state.limiter.check(request.client.host if request.client else "unknown")


def failure(error: Exception) -> HTTPException:
    if isinstance(error, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    if isinstance(error, NotReady):
        return HTTPException(status.HTTP_409_CONFLICT, str(error))
    if isinstance(error, ConfigError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The model service is not configured.")
    if isinstance(error, NotABillError):
        return HTTPException(422, str(error))
    if isinstance(error, ExtractionError):
        return HTTPException(422, str(error))
    raise error


@router.get("/samples", response_model=list[SampleView])
def list_samples(service: Service) -> list[SampleView]:
    return service.samples()


@router.post("/cases/sample/{name}", response_model=CaseView, status_code=201, dependencies=[Depends(limit_creations)])
def create_sample_case(name: str, service: Service) -> CaseView:
    try:
        return service.view(service.create_from_sample(name))
    except (NotFound, ConfigError, ExtractionError) as error:
        raise failure(error) from None


def save_upload(upload: UploadFile, limit: int, directory: Path) -> Path:
    """Stream to a temp file under a generated name (never the client's), refusing anything over `limit`."""
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in SUFFIX_KINDS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a PDF, PNG or JPEG.")
    handle = tempfile.NamedTemporaryFile(dir=directory, suffix=suffix, delete=False)
    path, size = Path(handle.name), 0
    try:
        with handle:
            while chunk := upload.file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, "That file is too large.")
                handle.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


@router.post("/cases", response_model=CaseView, status_code=201, dependencies=[Depends(limit_creations)])
def create_case(
    request: Request,
    service: Service,
    patient_type: Annotated[str, Form()],
    bill: Annotated[UploadFile, File()],
    eob: Annotated[UploadFile | None, File()] = None,
    gfe_total: Annotated[str | None, Form()] = None,
) -> CaseView:
    if patient_type not in {"self_pay", "insured"}:
        raise HTTPException(422, "patient_type must be self_pay or insured.")
    try:
        gfe = Decimal(gfe_total) if gfe_total else None
    except InvalidOperation:
        raise HTTPException(422, "The estimate must be a number.") from None
    if gfe is not None and not (Decimal(0) <= gfe <= Decimal(10_000_000)):
        raise HTTPException(422, "The estimate must be between 0 and 10,000,000.")

    limit = service.settings.max_upload_bytes
    paths: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="claimguard-") as scratch:
        try:
            paths.append(save_upload(bill, limit, Path(scratch)))
            if eob is not None and eob.filename:
                paths.append(save_upload(eob, limit, Path(scratch)))
            try:
                case_id = service.create(patient_type, gfe, paths[0], paths[1] if len(paths) > 1 else None)
            except (ConfigError, ExtractionError) as error:
                raise failure(error) from None
        finally:
            for path in paths:
                path.unlink(missing_ok=True)
    return service.view(case_id)


@router.get("/cases/{case_id}", response_model=CaseView)
def get_case(case_id: str, service: Service) -> CaseView:
    try:
        return service.view(case_id)
    except NotFound as error:
        raise failure(error) from None


@router.put("/cases/{case_id}/lines", response_model=CaseView)
def confirm_lines(case_id: str, body: ConfirmRequest, service: Service) -> CaseView:
    try:
        service.confirm(case_id, body)
        return service.view(case_id)
    except (NotFound, ConfigError) as error:
        raise failure(error) from None


@router.post("/cases/{case_id}/lookup", response_model=CaseView, dependencies=[Depends(limit_lookups)])
def look_up_hospital(case_id: str, service: Service, body: LookupRequest | None = None) -> CaseView:
    try:
        service.lookup(case_id, body.hospital_name if body else None)
        return service.view(case_id)
    except (NotFound, NotReady) as error:
        raise failure(error) from None


@router.post("/cases/{case_id}/letters", response_model=list[LetterView])
def make_letters(case_id: str, service: Service) -> list[LetterView]:
    try:
        return service.letter_views(case_id, service.letters(case_id))
    except (NotFound, NotReady) as error:
        raise failure(error) from None


@router.get("/cases/{case_id}/letters/{kind}.pdf")
def download_letter(case_id: str, kind: str, service: Service) -> Response:
    from app.letters.render import render_pdf

    try:
        letter = service.letter(case_id, kind)
    except (NotFound, NotReady) as error:
        raise failure(error) from None
    try:
        pdf = render_pdf(letter)
    except OSError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "PDF output is not available on this server.") from None
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{kind}.pdf"'}
    )
