import os
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("NEXAR_CLIENT_ID")
CLIENT_SECRET = os.getenv("NEXAR_CLIENT_SECRET")

TOKEN_URL = "https://identity.nexar.com/connect/token"
GRAPHQL_URL = "https://api.nexar.com/graphql"


def get_access_token():
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=15
    )

    response.raise_for_status()

    return response.json()["access_token"]


def search_component(part_number: str):
    token = get_access_token()

    query = """
    query SearchComponent($q: String!) {
      supSearch(q: $q, limit: 5) {
        results {
          part {
            mpn
            manufacturer {
              name
            }
            descriptions {
              text
            }
            specs {
              attribute {
                name
              }
              displayValue
            }
          }
        }
      }
    }
    """

    response = requests.post(
        GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={
            "query": query,
            "variables": {
                "q": part_number
            }
        },
        timeout=20
    )

    response.raise_for_status()

    result = response.json()

    if "errors" in result:
        raise RuntimeError(result["errors"])

    return result["data"]["supSearch"]["results"]