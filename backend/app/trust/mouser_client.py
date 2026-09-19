import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("MOUSER_API_KEY")

SEARCH_URL = (
    "https://api.mouser.com/api/v1/search/partnumber"
)


def search_component(part_number: str):
    if not API_KEY:
        raise RuntimeError("MOUSER_API_KEY is missing")

    response = requests.post(
        SEARCH_URL,
        params={"apiKey": API_KEY},
        json={
            "SearchByPartRequest": {
                "mouserPartNumber": part_number,
                "partSearchOptions": "None"
            }
        },
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    errors = data.get("Errors")
    if errors:
        raise RuntimeError(errors)

    parts = (
        data
        .get("SearchResults", {})
        .get("Parts", [])
    )

    return parts