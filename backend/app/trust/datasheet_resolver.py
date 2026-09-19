from typing import Optional
import requests


def verify_pdf_url(url: str) -> bool:
    if not url:
        return False

    try:
        response = requests.get(
            url,
            timeout=15,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        return (
            response.status_code == 200
            and response.content.startswith(b"%PDF")
        )

    except requests.RequestException:
        return False


def resolve_datasheet(
    manufacturer: str,
    part_number: str,
    mouser_url: Optional[str] = None
) -> dict:

    candidates = []

    if mouser_url:
        candidates.append({
            "url": mouser_url,
            "source": "mouser"
        })

    for candidate in candidates:
        if verify_pdf_url(candidate["url"]):
            return {
                "manufacturer": manufacturer,
                "part_number": part_number,
                "official_datasheet_url": candidate["url"],
                "source": candidate["source"],
                "verified_pdf": True
            }

    return {
        "manufacturer": manufacturer,
        "part_number": part_number,
        "official_datasheet_url": None,
        "source": None,
        "verified_pdf": False
    }