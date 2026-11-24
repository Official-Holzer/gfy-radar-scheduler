"""Read dated Amazon-seller facts from public German product tables."""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lxml import html

AGENT = "GFY-Preisradar/1.0 (ChatGPT-User/1.0; +https://gfy-radar.pages.dev/datenschutz)"
LABELS = ["Gemeldeter Tiefstpreis", "Gemeldeter Höchstpreis", "Gemeldeter Preis"]
ROOT = Path(__file__).resolve().parent.parent


def read_points(asin):
    url = f"https://de.camelcamelcamel.com/product/{asin}"
    try:
        with urlopen(Request(url, headers={"User-Agent": AGENT}), timeout=20) as response:
            body = response.read(2_000_001)
            if response.headers.get("cf-mitigated") == "challenge":
                raise RuntimeError("Browser challenge; stopping batch.")
    except HTTPError as exc:
        if exc.code in (404, 410):
            return []
        raise
    if len(body) > 2_000_000:
        raise ValueError("Oversized response")
    doc = html.fromstring(body.decode("utf-8"))
    if doc.xpath("//title[contains(., 'Just a moment')]") or b'challenge-platform' in body and not doc.xpath("//link[@rel='canonical']"):
        raise RuntimeError("Browser challenge; stopping batch.")
    if url not in doc.xpath("//link[@rel='canonical']/@href"):
        return []
    for table in doc.xpath("//table[.//tr[@data-field='amazon']]"):
        headings = [" ".join(th.text_content().split()) for th in table.xpath("./thead/tr/th")]
        if headings[:4] != ["Price Type", "Lowest Ever", "Highest Ever", "Current +"]:
            continue
        cells = table.xpath("./tbody/tr[@data-field='amazon']/td")
        if len(cells) < 4 or cells[0].text_content().strip() != "Amazon":
            continue
        points = []
        for label, cell in zip(LABELS, cells[1:4]):
            value = " ".join(cell.text_content().split())
            match = re.fullmatch(r"(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*€\s*\(([A-Z][a-z]{2} \d{1,2}, \d{4})\)", value)
            if match:
                cents = int(match[1].replace(".", "") + match[2])
                if cents > 0:
                    points.append(dict(date=datetime.strptime(match[3], "%b %d, %Y").date().isoformat(), cents=cents, label=label))
        return sorted(points, key=lambda p: p["date"])
    return []


if __name__ == "__main__":
    start = int(sys.argv[1])
    count = int(sys.argv[2])
    catalog = json.loads((ROOT / "catalog.json").read_text())
    if not (0 <= start < len(catalog) and 1 <= count <= 100):
        raise ValueError("Invalid catalog range")
    for i, item in enumerate(catalog[start:start+count]):
        if i:
            time.sleep(5)
        asin = item["id"]
        if not re.fullmatch("[A-Z0-9]{10}", asin):
            raise ValueError("Invalid ASIN")
        points = read_points(asin)
        print("REFERENCE " + json.dumps({"asin": asin, "points": points}), flush=True)
