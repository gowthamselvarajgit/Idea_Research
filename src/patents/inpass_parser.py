"""Response parser for Indian Patent Office InPASS PatentDetails HTML payloads.

Parses raw HTML responses from the InPASS publication/patent search system and maps
patent details into the canonical immutable InPassPatentRecord model.
"""

from dataclasses import dataclass, field
import html
from html.parser import HTMLParser
import logging
import re
from typing import Any, Optional, Sequence, Union

from src.patents.base_client import PatentClientError
from src.patents.models import InPassPatentRecord, PersonOrOrganization

logger = logging.getLogger(__name__)


class InPassParserError(PatentClientError):
    """Raised when InPASS PatentDetails HTML is invalid, empty, or unparseable."""
    pass


# HTML tags that do not require closing tags
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

# Tags whose opening implicitly closes currently open tags of certain types
_IMPLICIT_CLOSE_TAGS = {
    "td": {"td", "th"},
    "th": {"td", "th"},
    "tr": {"tr", "td", "th"},
    "tbody": {"tr", "td", "th"},
    "thead": {"tr", "td", "th"},
    "tfoot": {"tr", "td", "th"},
    "li": {"li"},
    "p": {"p"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
}

# Normalized field label mappings
_APPLICATION_NUMBER_ALIASES = {
    "application number",
    "application no",
    "application no.",
    "app number",
    "app no",
    "app no.",
}

_PUBLICATION_NUMBER_ALIASES = {
    "publication number",
    "publication no",
    "publication no.",
    "pub number",
    "pub no",
    "pub no.",
}

_PUBLICATION_DATE_ALIASES = {
    "publication date",
    "date of publication",
    "pub date",
    "publication date (u/s 11a)",
}

_FILING_DATE_ALIASES = {
    "filing date",
    "date of filing",
    "application date",
    "date of application",
    "application filing date",
}

_TITLE_ALIASES = {
    "title",
    "invention title",
    "title of invention",
}

_IPC_ALIASES = {
    "ipc",
    "international classification",
    "ipc classification",
    "international patent classification",
    "classification",
    "classification (ipc)",
}

_ABSTRACT_ALIASES = {
    "abstract",
    "patent abstract",
}

_SPECIFICATION_ALIASES = {
    "complete specification",
    "specification",
    "provisional / complete specification",
    "provisional/complete specification",
    "description",
}

_CLAIMS_ALIASES = {
    "claims",
    "claim",
    "patent claims",
}


def _is_applicant_header(text: str) -> bool:
    """Check if header text represents an applicant section while avoiding 'application' labels."""
    cleaned = text.strip().lower().rstrip(":")
    if cleaned in ("applicant", "applicants", "applicant(s)", "name of applicant", "name of applicant(s)", "applicant details"):
        return True
    return cleaned.startswith("applicant") and not cleaned.startswith("application")


def _is_inventor_header(text: str) -> bool:
    """Check if header text represents an inventor section."""
    cleaned = text.strip().lower().rstrip(":")
    if cleaned in ("inventor", "inventors", "inventor(s)", "name of inventor", "name of inventor(s)", "inventor details"):
        return True
    return cleaned.startswith("inventor")


class _HTMLNode:
    """Lightweight DOM tree node for robust HTML traversal."""

    def __init__(
        self,
        tag: str,
        attrs: dict[str, str],
        parent: Optional["_HTMLNode"] = None,
    ) -> None:
        self.tag = tag.lower()
        self.attrs = {k.lower(): v for k, v in attrs.items()}
        self.parent = parent
        self.children: list[Union["_HTMLNode", str]] = []

    def text_content(self, preserve_newlines: bool = False) -> str:
        """Extract clean text content recursively, optionally preserving linebreaks."""
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif isinstance(child, _HTMLNode):
                child_text = child.text_content(preserve_newlines=preserve_newlines)
                if preserve_newlines:
                    if child.tag == "br":
                        parts.append("\n")
                    elif child.tag in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
                        parts.append("\n" + child_text + "\n")
                    else:
                        parts.append(child_text)
                else:
                    parts.append(child_text)

        raw = html.unescape("".join(parts))
        if preserve_newlines:
            lines = [line.strip() for line in raw.split("\n")]
            cleaned_lines: list[str] = []
            prev_empty = False
            for line in lines:
                if not line:
                    if not prev_empty:
                        cleaned_lines.append("")
                        prev_empty = True
                else:
                    cleaned_lines.append(line)
                    prev_empty = False
            return "\n".join(cleaned_lines).strip()
        else:
            return " ".join(raw.split())

    def find_all(self, tag_name: str) -> list["_HTMLNode"]:
        """Find all descendant nodes matching tag_name."""
        tag_lower = tag_name.lower()
        results: list["_HTMLNode"] = []
        for child in self.children:
            if isinstance(child, _HTMLNode):
                if child.tag == tag_lower:
                    results.append(child)
                results.extend(child.find_all(tag_name))
        return results

    def find(self, tag_name: str) -> Optional["_HTMLNode"]:
        """Find first descendant node matching tag_name."""
        tag_lower = tag_name.lower()
        for child in self.children:
            if isinstance(child, _HTMLNode):
                if child.tag == tag_lower:
                    return child
                found = child.find(tag_name)
                if found is not None:
                    return found
        return None

    def get_element_by_id(self, elem_id: str) -> Optional["_HTMLNode"]:
        """Find descendant node with matching id attribute."""
        target = elem_id.lower()
        if self.attrs.get("id", "").lower() == target:
            return self
        for child in self.children:
            if isinstance(child, _HTMLNode):
                found = child.get_element_by_id(elem_id)
                if found is not None:
                    return found
        return None


class _DOMParser(HTMLParser):
    """Robust HTMLParser implementation that builds an in-memory node tree."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HTMLNode("root", {})
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()

        # Handle implicit element closing (e.g. unclosed <td>, <tr>, <p>)
        if tag_lower in _IMPLICIT_CLOSE_TAGS:
            close_set = _IMPLICIT_CLOSE_TAGS[tag_lower]
            while self.current and self.current.tag in close_set:
                self.current = self.current.parent or self.root

        attr_dict = {k: v or "" for k, v in attrs}
        node = _HTMLNode(tag_lower, attr_dict, parent=self.current)
        self.current.children.append(node)

        if tag_lower not in _VOID_TAGS:
            self.current = node

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        p: Optional[_HTMLNode] = self.current
        while p and p.tag != "root":
            if p.tag == tag_lower:
                self.current = p.parent or self.root
                break
            p = p.parent

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def _get_direct_rows(table_node: _HTMLNode) -> list[_HTMLNode]:
    """Retrieve top-level tr rows for a table (including direct tbody/thead children)."""
    rows: list[_HTMLNode] = [c for c in table_node.children if isinstance(c, _HTMLNode) and c.tag == "tr"]
    if not rows:
        for section in table_node.children:
            if isinstance(section, _HTMLNode) and section.tag in ("tbody", "thead"):
                rows.extend([c for c in section.children if isinstance(c, _HTMLNode) and c.tag == "tr"])
    return rows


def _parse_entities_table(table_node: _HTMLNode) -> list[PersonOrOrganization]:
    """Extract structured PersonOrOrganization records from an applicant/inventor nested table."""
    entities: list[PersonOrOrganization] = []
    trs = _get_direct_rows(table_node)
    if not trs:
        trs = table_node.find_all("tr")

    if not trs:
        return entities

    col_map = {"name": 0, "address": 1, "country": 2, "nationality": 3}
    header_found = False

    for tr in trs:
        cells = [c for c in tr.children if isinstance(c, _HTMLNode) and c.tag in ("td", "th")]
        if not cells:
            continue

        cell_texts = [c.text_content().strip() for c in cells]
        if not any(cell_texts):
            continue

        lower_texts = [t.lower() for t in cell_texts]

        # Check if row is a header row
        is_header = any(
            any(kw in t for kw in ("name", "address", "country", "nationality", "s.no", "sl no", "sl.no", "#"))
            for t in lower_texts
        )

        if is_header and not header_found:
            # Map column positions dynamically
            for idx, text in enumerate(lower_texts):
                if "name" in text and "applicant" in text:
                    col_map["name"] = idx
                elif "name" in text and "inventor" in text:
                    col_map["name"] = idx
                elif "name" in text and "name" not in [k for k, v in col_map.items() if v == idx]:
                    col_map["name"] = idx
                elif "address" in text:
                    col_map["address"] = idx
                elif "country" in text:
                    col_map["country"] = idx
                elif "nationality" in text:
                    col_map["nationality"] = idx
            header_found = True
            continue

        # If serial number is first column and no header detected yet, shift
        if not header_found and cell_texts[0].isdigit() and len(cell_texts) >= 5:
            col_map = {"name": 1, "address": 2, "country": 3, "nationality": 4}

        # Extract record
        name_idx = col_map.get("name", 0)
        addr_idx = col_map.get("address", 1)
        country_idx = col_map.get("country", 2)
        nat_idx = col_map.get("nationality", 3)

        name = cell_texts[name_idx] if name_idx < len(cell_texts) else ""
        address = cell_texts[addr_idx] if addr_idx < len(cell_texts) else ""
        country = cell_texts[country_idx] if country_idx < len(cell_texts) else ""
        nationality = cell_texts[nat_idx] if nat_idx < len(cell_texts) else ""

        # Validate name is non-empty and not a repeat header
        if name and name.lower() not in ("name", "applicant", "inventor", "name of applicant", "name of inventor"):
            entities.append(
                PersonOrOrganization(
                    name=name,
                    address=address,
                    country=country,
                    nationality=nationality,
                )
            )

    return entities


def parse_inpass_patent_details(
    html_content: Union[str, bytes],
    source_url: Optional[str] = None,
) -> InPassPatentRecord:
    """Parse InPASS PatentDetails HTML and construct an InPassPatentRecord.

    Args:
        html_content: Raw HTML string or bytes returned by InPASS PatentDetails endpoint.
        source_url: Optional verified source URL for the patent.

    Returns:
        InPassPatentRecord: Structured and validated immutable patent record.

    Raises:
        InPassParserError: If HTML is empty, malformed, or missing required application_number.
    """
    if html_content is None:
        raise InPassParserError("HTML content is None.")

    if isinstance(html_content, bytes):
        html_str = html_content.decode("utf-8", errors="replace")
    else:
        html_str = html_content

    if not html_str or not html_str.strip():
        raise InPassParserError("InPASS PatentDetails HTML payload is empty.")

    dom_parser = _DOMParser()
    try:
        dom_parser.feed(html_str)
    except Exception as err:
        raise InPassParserError(f"Failed to parse HTML document: {err}") from err

    root = dom_parser.root

    # Dictionary to collect parsed standard metadata
    metadata: dict[str, str] = {}
    applicants: list[PersonOrOrganization] = []
    inventors: list[PersonOrOrganization] = []
    raw_extracted: dict[str, Any] = {}

    abstract: Optional[str] = None
    specification: Optional[str] = None
    claims: Optional[str] = None

    all_tables = root.find_all("table")

    for table in all_tables:
        direct_rows = _get_direct_rows(table)
        num_rows = len(direct_rows)

        for i, row in enumerate(direct_rows):
            cells = [c for c in row.children if isinstance(c, _HTMLNode) and c.tag in ("td", "th")]
            if not cells:
                continue

            # Case A: Standard 2-cell key-value row
            if len(cells) == 2:
                key = cells[0].text_content().strip().lower().rstrip(":")
                val = cells[1].text_content().strip()
                raw_extracted[key] = val

                if key in _APPLICATION_NUMBER_ALIASES and "application_number" not in metadata:
                    metadata["application_number"] = val
                elif key in _PUBLICATION_NUMBER_ALIASES and "publication_number" not in metadata:
                    metadata["publication_number"] = val
                elif key in _PUBLICATION_DATE_ALIASES and "publication_date" not in metadata:
                    metadata["publication_date"] = val
                elif key in _FILING_DATE_ALIASES and "filing_date" not in metadata:
                    metadata["filing_date"] = val
                elif key in _TITLE_ALIASES and "title" not in metadata:
                    metadata["title"] = val
                elif key in _IPC_ALIASES and "ipc" not in metadata:
                    metadata["ipc"] = val
                elif key in _ABSTRACT_ALIASES and not abstract:
                    abstract = cells[1].text_content(preserve_newlines=True).strip()
                elif key in _SPECIFICATION_ALIASES and not specification:
                    specification = cells[1].text_content(preserve_newlines=True).strip()
                elif key in _CLAIMS_ALIASES and not claims:
                    claims = cells[1].text_content(preserve_newlines=True).strip()

            # Case B: Header or spanning row (e.g. Applicant, Inventor, Abstract, Specification, Claims)
            elif len(cells) == 1:
                header_text = cells[0].text_content().strip().lower().rstrip(":")

                # 1. Applicant section
                if _is_applicant_header(header_text) and not applicants:
                    # Look for nested table in current or upcoming rows
                    for look_idx in range(i, min(i + 3, num_rows)):
                        cand_row = direct_rows[look_idx]
                        subtables = cand_row.find_all("table")
                        if subtables:
                            applicants = _parse_entities_table(subtables[0])
                            break

                # 2. Inventor section
                elif _is_inventor_header(header_text) and not inventors:
                    for look_idx in range(i, min(i + 3, num_rows)):
                        cand_row = direct_rows[look_idx]
                        subtables = cand_row.find_all("table")
                        if subtables:
                            inventors = _parse_entities_table(subtables[0])
                            break

                # 3. Abstract section header / container
                elif not abstract and (
                    header_text in _ABSTRACT_ALIASES
                    or re.match(r"^abstract\s*:", cells[0].text_content().strip(), re.I)
                ):
                    cell_text = cells[0].text_content(preserve_newlines=True).strip()
                    if re.match(r"^abstract\s*:\s*", cell_text, re.I):
                        # Real InPASS layout: label and body in the same cell
                        abstract = re.sub(r"^abstract\s*:\s*", "", cell_text, flags=re.I).strip()
                    elif header_text in _ABSTRACT_ALIASES and i + 1 < num_rows:
                        # Synthetic/legacy layout: pure header row, body in next row
                        next_row = direct_rows[i + 1]
                        if not next_row.find_all("table"):
                            abstract = next_row.text_content(preserve_newlines=True).strip()

                # 4. Specification section header / container
                elif (
                    header_text in _SPECIFICATION_ALIASES
                    or "complete specification" in header_text
                ) and not specification:
                    # Check if there is a textarea in current cell (real InPASS structure)
                    tas = cells[0].find_all("textarea")
                    if tas:
                        full_spec_text = tas[0].text_content(preserve_newlines=True).strip()
                        if ", Claims:" in full_spec_text:
                            parts = full_spec_text.split(", Claims:", 1)
                            specification = parts[0].strip()
                            if not claims and len(parts) > 1:
                                claims = parts[1].strip()
                        elif "Claims:" in full_spec_text:
                            parts = full_spec_text.split("Claims:", 1)
                            specification = parts[0].strip()
                            if not claims and len(parts) > 1:
                                claims = parts[1].strip()
                        else:
                            specification = full_spec_text
                    elif i + 1 < num_rows:
                        # Synthetic/legacy layout: pure header row, body in next row
                        next_row = direct_rows[i + 1]
                        if not next_row.find_all("table"):
                            specification = next_row.text_content(preserve_newlines=True).strip()

                # 5. Claims section header
                elif header_text in _CLAIMS_ALIASES and not claims:
                    if i + 1 < num_rows:
                        next_row = direct_rows[i + 1]
                        if not next_row.find_all("table"):
                            claims = next_row.text_content(preserve_newlines=True).strip()

    # Fallback element lookup by ID / attributes if not resolved from tables
    if "application_number" not in metadata:
        app_elem = root.get_element_by_id("ApplicationNumber") or root.get_element_by_id("application_number")
        if app_elem is not None:
            val = app_elem.attrs.get("value") or app_elem.text_content()
            if val and val.strip():
                metadata["application_number"] = val.strip()

    if "title" not in metadata:
        title_elem = root.get_element_by_id("InventionTitle") or root.get_element_by_id("title")
        if title_elem is not None:
            metadata["title"] = title_elem.text_content().strip()

    if not abstract:
        abs_node = root.get_element_by_id("abstract") or root.get_element_by_id("Abstract")
        if abs_node is not None:
            abstract = abs_node.text_content(preserve_newlines=True).strip()

    if not specification or not claims:
        spec_node = (
            root.get_element_by_id("COMPLETE_SPECIFICATION")
            or root.get_element_by_id("complete_specification")
            or root.get_element_by_id("CompleteSpecification")
            or root.get_element_by_id("specification")
            or root.get_element_by_id("spec")
        )
        if spec_node is None:
            for ta in root.find_all("textarea"):
                ta_id = ta.attrs.get("id", "").lower()
                ta_class = ta.attrs.get("class", "").lower()
                if "complete_specification" in ta_id or "complete-specification" in ta_class or not spec_node:
                    spec_node = ta
                    break

        if spec_node is not None:
            full_text = spec_node.text_content(preserve_newlines=True).strip()
            if not specification:
                if ", Claims:" in full_text:
                    parts = full_text.split(", Claims:", 1)
                    specification = parts[0].strip()
                    if not claims and len(parts) > 1:
                        claims = parts[1].strip()
                elif "Claims:" in full_text:
                    parts = full_text.split("Claims:", 1)
                    specification = parts[0].strip()
                    if not claims and len(parts) > 1:
                        claims = parts[1].strip()
                else:
                    specification = full_text
            elif not claims and (", Claims:" in full_text or "Claims:" in full_text):
                if ", Claims:" in full_text:
                    claims = full_text.split(", Claims:", 1)[1].strip()
                elif "Claims:" in full_text:
                    claims = full_text.split("Claims:", 1)[1].strip()

    if not claims:
        claims_node = root.get_element_by_id("claims") or root.get_element_by_id("Claims")
        if claims_node is not None:
            claims = claims_node.text_content(preserve_newlines=True).strip()

    # Safety check: if specification contains ", Claims:" and claims is still unset
    if specification and not claims:
        if ", Claims:" in specification:
            parts = specification.split(", Claims:", 1)
            specification = parts[0].strip()
            claims = parts[1].strip()
        elif "Claims:" in specification:
            parts = specification.split("Claims:", 1)
            specification = parts[0].strip()
            claims = parts[1].strip()

    # Application number is strictly required
    app_num = metadata.get("application_number", "").strip()
    if not app_num:
        raise InPassParserError("Missing required Application Number in InPASS PatentDetails HTML.")

    raw_extracted["parsed_applicants_count"] = len(applicants)
    raw_extracted["parsed_inventors_count"] = len(inventors)

    return InPassPatentRecord(
        application_number=app_num,
        publication_number=metadata.get("publication_number"),
        publication_date=metadata.get("publication_date"),
        filing_date=metadata.get("filing_date"),
        title=metadata.get("title", ""),
        ipc=metadata.get("ipc"),
        abstract=abstract if abstract else None,
        specification=specification if specification else None,
        claims=claims if claims else None,
        applicants=applicants,
        inventors=inventors,
        source="INPASS",
        source_url=source_url or "",
        raw_data=raw_extracted,
    )


# Alias
parse_inpass_details = parse_inpass_patent_details
