import hmac
import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("PORT", "8080"))
SECRET = os.environ.get("OFFICE_CONVERTER_SECRET", "")
MAX_BYTES = int(os.environ.get("MAX_OFFICE_BYTES", str(100 * 1024 * 1024)))
CONVERSION_TIMEOUT = int(os.environ.get("CONVERSION_TIMEOUT_SECONDS", "600"))
ALLOWED_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
CONVERSION_SLOTS = threading.BoundedSemaphore(
    int(os.environ.get("MAX_CONCURRENT_CONVERSIONS", "2"))
)


class ConversionError(Exception):
    pass


def validate_url(raw_url: str) -> str:
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConversionError("Only HTTPS signed URLs are accepted")
    return raw_url


def download_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "hortus-office-converter"})
    with urllib.request.urlopen(request, timeout=120) as response:
        declared_size = response.headers.get("Content-Length")
        if declared_size and int(declared_size) > MAX_BYTES:
            raise ConversionError("Source document exceeds the size limit")

        written = 0
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_BYTES:
                    raise ConversionError("Source document exceeds the size limit")
                output.write(chunk)


def convert_to_pdf(source: Path, output_dir: Path, profile_dir: Path) -> Path:
    command = [
        "soffice",
        "--headless",
        "--nologo",
        "--nodefault",
        "--nolockcheck",
        "--norestore",
        f"-env:UserInstallation={profile_dir.as_uri()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=CONVERSION_TIMEOUT,
        check=False,
    )
    expected = output_dir / f"{source.stem}.pdf"
    if result.returncode != 0 or not expected.is_file() or expected.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "no PDF was produced").strip()
        raise ConversionError(f"LibreOffice conversion failed: {detail[:500]}")
    return expected


def upload_pdf(url: str, pdf_path: Path) -> None:
    data = pdf_path.read_bytes()
    request = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={
            "Content-Type": "application/pdf",
            "Content-Length": str(len(data)),
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        if response.status < 200 or response.status >= 300:
            raise ConversionError(f"Destination upload returned {response.status}")


class Handler(BaseHTTPRequestHandler):
    server_version = "HortusOfficeConverter/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {"ok": True})
            return
        self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/convert":
            self.send_json(404, {"error": "Not found"})
            return
        if not SECRET:
            self.send_json(503, {"error": "Converter secret is not configured"})
            return

        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {SECRET}"
        if not hmac.compare_digest(supplied, expected):
            self.send_json(401, {"error": "Unauthorized"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 64 * 1024:
                raise ConversionError("Invalid request size")
            payload = json.loads(self.rfile.read(content_length))
            source_url = validate_url(str(payload.get("sourceUrl", "")))
            destination_url = validate_url(str(payload.get("destinationUrl", "")))
            filename = Path(str(payload.get("filename", ""))).name
            extension = Path(filename).suffix.lower()
            if extension not in ALLOWED_EXTENSIONS:
                raise ConversionError("Unsupported Office file type")

            with CONVERSION_SLOTS:
                with tempfile.TemporaryDirectory(prefix="hortus-office-") as temp:
                    root = Path(temp)
                    source = root / f"source{extension}"
                    output_dir = root / "output"
                    profile_dir = root / "profile"
                    output_dir.mkdir()
                    profile_dir.mkdir()
                    download_file(source_url, source)
                    pdf = convert_to_pdf(source, output_dir, profile_dir)
                    upload_pdf(destination_url, pdf)

            self.send_json(200, {"ok": True})
        except (ConversionError, ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except subprocess.TimeoutExpired:
            self.send_json(504, {"error": "Office conversion timed out"})
        except Exception:
            self.send_json(500, {"error": "Office conversion failed"})

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"{self.address_string()} - {format_string % args}", flush=True)

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if shutil.which("soffice") is None:
        raise RuntimeError("LibreOffice soffice binary was not found")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
