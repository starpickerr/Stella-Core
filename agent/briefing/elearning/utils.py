"""Text and date helpers adapted from elearning_crawler/src/utils.py."""
import datetime as dt
import re
from html.parser import HTMLParser

SHANGHAI = dt.timezone(dt.timedelta(hours=8))

def parse_date(value):
    if not value:
        return None
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=dt.timezone.utc) if result.tzinfo is None else result
    except (ValueError, AttributeError):
        return None


def display_date(value):
    parsed = parse_date(value)
    return parsed.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M") if parsed else "未设置"


def md(value):
    return re.sub(r"([\\`*_[\]<>|])", r"\\\1", str(value)).replace("\n", " ")


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.skip = [], [], 0
        self.file_references = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if self.skip:
            return
        if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")
        if tag == "a":
            attributes = dict(attrs)
            href = attributes.get("href", "")
            if href:
                self.links.append(href)
                self.file_references.append(href)
            if attributes.get("data-api-endpoint"):
                self.file_references.append(attributes["data-api-endpoint"])
        if tag == "img":
            attributes = dict(attrs)
            for key in ("src", "data-api-endpoint"):
                if attributes.get(key):
                    self.file_references.append(attributes[key])
            if attributes.get("src"):
                self.links.append(attributes["src"])
            if attributes.get("alt"):
                self.parts.append(attributes["alt"])

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if not self.skip and tag in ("p", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def extract(html):
    parser = TextExtractor()
    parser.feed(html or "")
    text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
    return text, list(dict.fromkeys(parser.links))


def next_link(header):
    for url, rel in re.findall(r'<([^>]+)>\s*;\s*rel="([^"]+)"', header or ""):
        if "next" in rel.split():
            return url
    return None
