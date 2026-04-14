import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_CONTEXT_LENGTH = 2000
SCRAPE_TIMEOUT = 5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AgencyHunter/1.0)",
    "Accept": "text/html",
    "Accept-Language": "fi,en;q=0.5",
}

# Poistetaan elementit jotka eivat sisalla hyodyllista leipatekstia
REMOVE_TAGS = {"script", "style", "nav", "header", "footer", "iframe", "noscript", "svg", "form"}


def scrape_website_text(url: str) -> Optional[str]:
    """Hakee verkkosivun leipatekstin. Palauttaa None jos epaonnistuu.

    - 5s timeout
    - Poistaa navigaatiot, scriptit, headerit, footerit
    - Palauttaa max 2000 merkkia siivottua tekstia
    """
    if not url:
        return None

    if not url.startswith("http"):
        url = f"http://{url}"

    try:
        resp = requests.get(url, timeout=SCRAPE_TIMEOUT, headers=HEADERS, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Deep Scan: sivun haku epaonnistui ({url}): {e}")
        return None

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        logger.info(f"Deep Scan: ei HTML-sisaltoa ({url}): {content_type}")
        return None

    try:
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup.find_all(REMOVE_TAGS):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)

        # Siivotaan ylimaaraiset valilyonnit
        cleaned = " ".join(text.split())

        if len(cleaned) < 30:
            logger.info(f"Deep Scan: liian vahan tekstia ({url}): {len(cleaned)} merkkia")
            return None

        return cleaned[:MAX_CONTEXT_LENGTH]

    except Exception as e:
        logger.warning(f"Deep Scan: HTML-parsinta epaonnistui ({url}): {e}")
        return None
