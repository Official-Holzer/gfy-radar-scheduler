"""Extract an unambiguous one-time offer for the selected Amazon.de ASIN."""
import re
import sys

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
            if subscription(offer):
                continue
            fields = offer.xpath(f".//*[{has_class('a-offscreen')}] | ./*[@aria-hidden='true']")
            for field in fields:
                match = re.fullmatch(r"(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*€", field.text_content().strip())
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

if __name__ == "__main__":
    page = sys.stdin.buffer.read().decode("utf-8-sig")
    doc = html.fromstring(page)
    if not is_selected_product(doc, sys.argv[1]):
        print("unmatched")
    else:
        print(price_in_cents(doc, sys.argv[1]) or "no-price")
