import html
import re
from bs4 import BeautifulSoup


def is_html_content(value: str) -> bool:
    if not value:
        return False

    return bool(
        re.search(
            r"<\s*(p|div|span|table|tr|td|ul|ol|li|a|img|br|blockquote|pre|code)\b",
            value,
            re.IGNORECASE,
        )
    )


def clean_jira_html(value) -> str:
    if value is None:
        return ""

    if not isinstance(value, str):
        return str(value)

    text = html.unescape(value)

    if not is_html_content(text):
        return _clean_plain_text(text)

    soup = BeautifulSoup(text, "html.parser")

    for tag in soup(["script", "style"]):
        tag.decompose()

    for img in soup.find_all("img"):
        alt = img.get("alt") or img.get("src") or "image"
        img.replace_with(f"\n[Image: {alt}]\n")

    for a in soup.find_all("a"):
        label = a.get_text(" ", strip=True)
        href = a.get("href")

        if label and href:
            a.replace_with(f"{label} ({href})")
        elif label:
            a.replace_with(label)
        elif href:
            a.replace_with(href)

    for br in soup.find_all("br"):
        br.replace_with("\n")

    text = soup.get_text("\n", strip=True)

    return _clean_plain_text(text)


def _clean_plain_text(text: str) -> str:
    text = html.unescape(text or "")

    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()