import os
import tempfile

# Must run before config.py is imported: isolate storage and force mock mode.
_tmp = tempfile.mkdtemp(prefix="labguard-test-")
os.environ["AI_PROVIDER"] = "mock"
os.environ["AGENT_INTERVAL_MINUTES"] = "0"  # tests trigger the proactive agent themselves
os.environ["STORAGE_DIR"] = os.path.join(_tmp, "storage")
os.environ["DATA_DIR"] = os.path.join(_tmp, "data")  # empty, so the backend seed is used

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def make_pdf(text: str) -> bytes:
    """Minimal one-page PDF with a line of text, for manual upload tests."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)
