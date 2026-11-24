"""Extract an unambiguous one-time offer for the selected Amazon.de ASIN."""
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from urllib.parse import urlsplit

from lxml import html


def has_class(name):
    return f"contains(concat(' ',normalize-space(@class),' '),' {name} ')"


def is_selected_product(doc, asin):
    selected = set(doc.xpath("//input[@id='ASIN']/@value"))
    if selected:
        return selected == {asin}
    for url in doc.xpath("//link[@rel='canonical']/@href"):
        address = urlsplit(url)
        if address.hostname in ("www.amazon.de", "amazon.de") and re.search(
                r"/(?:dp|gp/product)/" + re.escape(asin) + r"/?$", address.path):
            return True
    return False


def subscription(element):
    return any(any(word in (node.get("id", "") + " " + node.get("action", "")).lower()
                   for word in ("sns", "subscri", "subscribe"))
               for node in (element, *element.iterancestors()))


def price_in_cents(doc, asin):
    if not is_selected_product(doc, asin):
        return None
    panels = doc.xpath("//*[@id='corePriceDisplay_desktop_feature_div' or @id='corePrice_feature_div']")
    prices = set()
    for panel in panels:
        if panel.get("data-csa-c-asin", asin) != asin:
            continue
        for offer in panel.xpath(f".//*[{has_class('priceToPay')}]"):
            if subscription(offer) or any(node.get("data-csa-c-asin", asin) != asin
                                          for node in (offer, *offer.iterancestors())):
                continue
            values = [node.text_content().strip() for node in
                      offer.xpath(f".//*[{has_class('a-offscreen')}] | ./*[@aria-hidden='true']")]
            parts = [offer.xpath(f".//*[{has_class(name)}]") for name in
                     ("a-price-whole", "a-price-fraction", "a-price-symbol")]
            if all(len(nodes) == 1 for nodes in parts):
                whole, fraction, symbol = [nodes[0].text_content().strip() for nodes in parts]
                values.append(whole.removesuffix(",") + "," + fraction + symbol)
            for value in values:
                match = re.fullmatch(r"(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*€", value)
                if match:
                    prices.add(int(match[1].replace(".", "")) * 100 + int(match[2]))
    # The buy box can also expose the selected offer as explicit currency and amount fields.
    for form in doc.xpath("//form[.//input[@name='ASIN' and @value=$asin]]", asin=asin):
        if subscription(form) or set(form.xpath(".//input[@name='ASIN']/@value")) != {asin}:
            continue
        currency = form.xpath(".//input[@name='items[0.base][customerVisiblePrice][currencyCode]']/@value")
        amounts = form.xpath(".//input[@name='items[0.base][customerVisiblePrice][amount]']/@value")
        if currency == ["EUR"] and len(amounts) == 1 and re.fullmatch(r"\d+\.\d{2}", amounts[0]):
            prices.add(int(amounts[0].replace(".", "")))
    return prices.pop() if len(prices) == 1 and min(prices) > 0 else None

def read_public_offer(asin):
    request = Request(f"https://www.amazon.de/dp/{asin}", headers={"Accept-Language": "de-DE"})
    try:
        with urlopen(request, timeout=8) as response:
            if urlsplit(response.url).hostname not in ("amazon.de", "www.amazon.de"):
                return "unmatched"
            body = response.read(6_000_001)
    except HTTPError as exc:
        return f"http-{exc.code}"
    except (URLError, TimeoutError, OSError):
        return "network-error"
    if len(body) > 6_000_000 or not body.strip():
        return "unreadable"
    doc = html.fromstring(body.decode("utf-8", errors="replace"))
    if doc.xpath("//input[@id='captchacharacters'] | //form[contains(@action,'validateCaptcha')]"):
        return "access-challenge"
    if not is_selected_product(doc, asin):
        return "unmatched"
    return price_in_cents(doc, asin) or "no-offer"


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--fetch":
    if not re.fullmatch("[A-Z0-9]{10}", sys.argv[2]):
        sys.exit("Invalid ASIN")
    print(read_public_offer(sys.argv[2]))
elif __name__ == "__main__":
    page = sys.stdin.buffer.read().decode("utf-8-sig")
    doc = html.fromstring(page)
    if not is_selected_product(doc, sys.argv[1]):
        print("unmatched")
    else:
        print(price_in_cents(doc, sys.argv[1]) or "no-price")
