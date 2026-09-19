import io
import requests
from pypdf import PdfReader


def extract_datasheet_text(url: str) -> str:
    if not url:
        raise ValueError("No datasheet URL provided")

    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
        allow_redirects=True
    )

    response.raise_for_status()

    content = response.content
    content_type = response.headers.get("Content-Type", "")

    print("Final URL:", response.url)
    print("Content-Type:", content_type)
    print("Downloaded bytes:", len(content))

    if not content.startswith(b"%PDF"):
        raise RuntimeError(
            f"Datasheet URL did not return a PDF. "
            f"Content-Type: {content_type}, "
            f"Final URL: {response.url}"
        )

    try:
        reader = PdfReader(
            io.BytesIO(content),
            strict=False
        )
    except Exception as e:
        raise RuntimeError(
            f"Downloaded PDF is invalid or incomplete: {e}"
        )

    pages = []

    for page in reader.pages:
        try:
            text = page.extract_text()
            if text:
                pages.append(text)
        except Exception:
            continue

    if not pages:
        raise RuntimeError(
            "PDF downloaded successfully but no text could be extracted"
        )

    return "\n".join(pages)