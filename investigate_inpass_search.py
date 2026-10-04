"""Temporary investigation script for Indian InPASS search endpoint."""

import re
from html.parser import HTMLParser
import requests

BASE_URL = "https://iprsearch.ipindia.gov.in/PublicSearch/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current_form = None

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag == "form":
            self.current_form = {
                "action": attr_dict.get("action", ""),
                "method": attr_dict.get("method", "GET").upper(),
                "inputs": {},
                "all_tags": [],
            }
            self.forms.append(self.current_form)
        elif self.current_form is not None:
            if tag in ("input", "select", "textarea"):
                name = attr_dict.get("name")
                if name:
                    self.current_form["inputs"][name] = {
                        "type": attr_dict.get("type", "text"),
                        "value": attr_dict.get("value", ""),
                    }
                    self.current_form["all_tags"].append((tag, name, attr_dict.get("type", "text"), attr_dict.get("value", "")))


def run_investigation():
    session = requests.Session()
    session.headers.update(HEADERS)

    print("Step 1: Fetching initial page via GET...")
    try:
        resp = session.get(BASE_URL, timeout=30)
    except Exception as e:
        print(f"Failed to fetch initial page: {e}")
        return

    print(f"Initial GET Status: {resp.status_code}")
    print(f"Initial GET URL: {resp.url}")

    parser = FormParser()
    parser.feed(resp.text)

    print(f"\nInitial GET HTML size: {len(resp.text)} bytes")
    # Check if there are iframes or frames
    frames = re.findall(r'<i?frame[^>]+src=["\']([^"\']+)["\']', resp.text, re.IGNORECASE)
    print(f"Frames detected: {frames}")

    # Check for all input tags anywhere in resp.text
    all_inputs = re.findall(r'<input[^>]+>', resp.text, re.IGNORECASE)
    print(f"Total <input> tags on page: {len(all_inputs)}")
    for inp in all_inputs[:10]:
        print(f"  {inp}")

    # Check for forms
    all_forms = re.findall(r'<form[^>]*>', resp.text, re.IGNORECASE)
    print(f"Total <form> tags: {len(all_forms)}")
    for f in all_forms:
        print(f"  {f}")
    captcha_field = None
    for name, info in form["inputs"].items():
        print(f"  - {name} (type={info['type']}, default={info['value']!r})")
        if "captcha" in name.lower():
            captcha_field = name

    # Resolve action URL
    action_url = form["action"]
    if not action_url.startswith("http"):
        if action_url.startswith("/"):
            action_url = "https://iprsearch.ipindia.gov.in" + action_url
        else:
            action_url = "https://iprsearch.ipindia.gov.in/PublicSearch/" + action_url

    print(f"\nTarget Search Endpoint: {action_url}")

    # Build search payload:
    # Search field: Title (TI)
    # Search text: WATER
    # Published: checked
    # Granted: unchecked
    # Date filter: none
    # Normal CAPTCHA handling only (no solving/bypassing)
    payload = {}
    for name, info in form["inputs"].items():
        payload[name] = info["value"]

    # Configure search specific fields
    # Look for publication/grant checkboxes or radios
    if "Published" in payload:
        payload["Published"] = "true"
    if "Granted" in payload:
        payload["Granted"] = "false"

    # Set Title search
    if "ItemField1" in payload:
        payload["ItemField1"] = "TI"
    if "TextField1" in payload:
        payload["TextField1"] = "WATER"

    print("\nStep 2: Sending ONE normal POST search request...")
    headers = {"Referer": resp.url}
    try:
        post_resp = session.post(action_url, data=payload, headers=headers, timeout=30)
    except Exception as e:
        print(f"POST request failed: {e}")
        return

    text = post_resp.text
    status = post_resp.status_code
    final_url = post_resp.url
    content_type = post_resp.headers.get("Content-Type", "Unknown")
    size = len(post_resp.content)

    lower = text.lower()
    is_captcha_error = any(
        phrase in lower
        for phrase in [
            "captcha",
            "invalid captcha",
            "enter captcha",
            "enter valid captcha",
            "captcha is required",
            "please enter the characters",
        ]
    )
    has_total_docs = "total document" in lower
    has_patent_details = "patentdetails" in lower or "patent details" in lower

    # Search for Indian patent application numbers like 202641113890 or 1234/DEL/2015 or IN202...
    app_num_pattern = re.compile(r"\b\d{12}\b|\b\d{1,5}/[A-Z]{3}/\d{4}\b")
    found_app_nums = app_num_pattern.findall(text)

    print("\n--- InPASS Search Investigation Report ---")
    print(f"HTTP Status: {status}")
    print(f"Final URL: {final_url}")
    print(f"Content-Type: {content_type}")
    print(f"Response Size: {size} bytes")
    print(f"CAPTCHA / Error Page: {is_captcha_error}")
    print(f"Contains 'Total Document(s)': {has_total_docs}")
    print(f"Contains 'PatentDetails': {has_patent_details}")
    print(f"Application number matches in response: {len(found_app_nums)} found")
    if found_app_nums:
        print(f"Sample matches: {found_app_nums[:5]}")

    # Analyze specific messages in the response
    print("\n--- Diagnostic Findings ---")
    if "captcha" in lower:
        # Extract snippets mentioning captcha
        matches = re.findall(r".{0,50}captcha.{0,50}", text, re.IGNORECASE)
        print(f"CAPTCHA snippets found ({len(matches)}):")
        for m in matches[:3]:
            print(f"  * {m.strip()}")

    if "total document" in lower:
        matches = re.findall(r".{0,40}total document.{0,40}", text, re.IGNORECASE)
        for m in matches[:2]:
            print(f"  * {m.strip()}")


if __name__ == "__main__":
    run_investigation()
