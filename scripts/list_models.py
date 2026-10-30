"""List the models Token Factory exposes to this API key. Run: python -m scripts.list_models [filter]"""

import os
import sys

from dotenv import load_dotenv
from openai import AuthenticationError, OpenAI

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


def main() -> None:
    load_dotenv()
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        raise SystemExit("NEBIUS_API_KEY is not set (see .env.example)")
    needle = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    try:
        models = OpenAI(base_url=BASE_URL, api_key=key).models.list()
    except AuthenticationError:
        raise SystemExit("Token Factory rejected the API key (401): check NEBIUS_API_KEY in .env") from None
    for model in sorted(models.data, key=lambda m: m.id):
        if needle in model.id.lower():
            print(model.id)


if __name__ == "__main__":
    main()
