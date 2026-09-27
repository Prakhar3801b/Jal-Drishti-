"""
Validate the running API's CAP 1.2 output against the official OASIS schema.

    pip install lxml
    python backend/scripts/validate_cap.py [http://localhost:8000]

Reads the Atom feed, fetches every message it lists, and checks each one against
CAP-v1.2.xsd (downloaded from docs.oasis-open.org, kept beside this script) plus
the rules in the CAP 1.2 spec that the schema cannot express. Exits non-zero on
the first run with any failure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
from lxml import etree

CAP = "{urn:oasis:names:tc:emergency:cap:1.2}"
ATOM = "{http://www.w3.org/2005/Atom}"
XSD = Path(__file__).with_name("CAP-v1.2.xsd")
FORBIDDEN = re.compile(r"[\s,<&]")


def spec_rules(doc: etree._Element) -> list[str]:
    """CAP 1.2 section 3.2 rules beyond the XSD."""
    errors = []
    for tag in ("identifier", "sender"):
        if FORBIDDEN.search(doc.findtext(CAP + tag) or ""):
            errors.append(f"{tag} contains a space, comma, '<' or '&'")
    refs = doc.findtext(CAP + "references")
    if doc.findtext(CAP + "msgType") in ("Update", "Cancel") and not refs:
        errors.append("Update/Cancel without references")
    for ref in (refs or "").split():
        if len(ref.split(",")) != 3:
            errors.append(f"reference '{ref}' is not sender,identifier,sent")
    if doc.findtext(CAP + "status") == "Actual":
        errors.append("prototype must not publish status Actual")
    for info in doc.iter(CAP + "info"):
        for circle in info.iter(CAP + "circle"):
            if not re.fullmatch(r"-?\d+(\.\d+)?,-?\d+(\.\d+)? \d+(\.\d+)?", circle.text or ""):
                errors.append(f"circle '{circle.text}' is not 'lat,lon radius'")
    return errors


def main(base: str) -> int:
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    with httpx.Client(base_url=base.rstrip("/"), timeout=60) as client:
        feed = etree.fromstring(client.get("/api/cap/feed.atom").raise_for_status().content)
        links = [
            e.find(ATOM + "link").get("href")
            for e in feed.iter(ATOM + "entry")
        ]
        print(f"feed lists {len(links)} CAP messages")
        failed = 0
        for href in links:
            doc = etree.fromstring(client.get(href).raise_for_status().content)
            errors = [] if schema.validate(doc) else [str(e) for e in schema.error_log]
            errors += spec_rules(doc)
            ident = doc.findtext(CAP + "identifier")
            if errors:
                failed += 1
                print(f"FAIL {ident}")
                for e in errors:
                    print(f"     {e}")
        print(f"{len(links) - failed}/{len(links)} valid CAP 1.2")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"))
