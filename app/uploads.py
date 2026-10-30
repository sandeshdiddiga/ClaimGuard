"""Limits on an uploaded bill or EOB, checked before anything reads it.

Messages never include the file name or any content: names and documents carry personal details.
"""

import logging
import stat
from pathlib import Path

import pdfplumber
from PIL import Image

# pdfminer logs the text of every page it parses at DEBUG level; keep document text out of any log.
for _name in ("pdfminer", "pdfplumber"):
    logging.getLogger(_name).setLevel(logging.WARNING)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PAGES = 5
MAX_IMAGE_PIXELS = 40_000_000
MAX_PAGE_POINTS = 1500  # about 21 inches: far beyond any bill; at 150 dpi a page stays near 10 megapixels

SUFFIX_KINDS = {".pdf": "pdf", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}
MAGIC = {"pdf": (b"%PDF-",), "png": (b"\x89PNG\r\n\x1a\n",), "jpeg": (b"\xff\xd8\xff",)}


class UploadError(ValueError):
    pass


def _open_error() -> UploadError:
    return UploadError("could not open this file; try a PDF or a clearer photo")


def check_upload(path: Path) -> str:
    """Validate an uploaded file and return its kind ('pdf', 'png' or 'jpeg')."""
    kind = SUFFIX_KINDS.get(path.suffix.lower())
    if kind is None:
        raise UploadError(f"unsupported file type: {path.suffix or 'none'}")
    try:
        info = path.lstat()
    except OSError:
        raise _open_error() from None
    if not stat.S_ISREG(info.st_mode):  # no symlinks, devices or directories
        raise _open_error()
    if info.st_size == 0:
        raise UploadError("this file is empty")
    if info.st_size > MAX_UPLOAD_BYTES:
        raise UploadError(f"this file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    with path.open("rb") as handle:
        head = handle.read(8)
    if not head.startswith(MAGIC[kind]):
        raise UploadError("the file content does not match its type")
    try:
        _check_structure(path, kind)
    except UploadError:
        raise
    except Exception:  # corrupt or hostile files raise anything; the cause is never shown
        raise _open_error() from None
    return kind


def _check_structure(path: Path, kind: str) -> None:
    if kind == "pdf":
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise UploadError(f"this PDF has more than {MAX_PAGES} pages")
            for page in pdf.pages:
                if page.width > MAX_PAGE_POINTS or page.height > MAX_PAGE_POINTS:
                    raise UploadError("the page size in this PDF is too large")
        return
    with Image.open(path) as image:  # reads the header only
        width, height = image.size
    if width * height > MAX_IMAGE_PIXELS:
        raise UploadError("this image is too large")
