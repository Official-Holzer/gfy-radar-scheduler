"""Extract an unambiguous one-time offer for the selected Amazon.de ASIN."""
import re
import sys

from lxml import html


def has_class(name):
    return f"contains(concat(' ',normalize-space(@class),' '),' {name} ')"


def price_in_cents(page, asin):
    doc = html.fromstring(page)
    if asin not in doc.xpath("//input[@id='ASIN']/@value"):
        return None
    panels = doc.xpath("//*[@id='corePriceDisplay_desktop_feature_div' or @id='corePrice_feature_div']")
    prices = set()
    for panel in panels:
        if panel.get("data-csa-c-asin", asin) != asin:
            continue
        for offer in panel.xpath(f".//*[{has_class('priceToPay')}]"):
            if any("sns" in p.get("id", "").lower() or "subscription" in p.get("id", "").lower()
                   for p in offer.iterancestors()):
                continue
            fields = offer.xpath(f".//*[{has_class('a-offscreen')}] | ./*[@aria-hidden='true']")
            for field in fields:
                match = re.fullmatch(r"(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*€", field.text_content().strip())
                if match:
                    prices.add(int(match[1].replace(".", "")) * 100 + int(match[2]))
    return prices.pop() if len(prices) == 1 else None

if __name__ == "__main__":
    page = sys.stdin.buffer.read().decode("utf-8-sig")
    price = price_in_cents(page, sys.argv[1])
    if price:
        print(price)
    else:
        doc = html.fromstring(page)
        print("Page title: " + doc.xpath("string(//title)")[:110].strip(), file=sys.stderr)
