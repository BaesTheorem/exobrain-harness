#!/usr/bin/env python3
"""Law-firm patterns shared by the /job-search lanes.

Alex's IT experience is at a law firm (iManage, Elite 3E, Intapp, attorney
support under billable-hour pressure), so law-firm IT seats get three things
from this module:

  LAW_TITLES   law-firm IT titles that the lanes' generic KEEP filters miss
               ("Litigation Support Specialist", "Practice Technology Analyst",
               "Technology Trainer", "Deskside Support"). Each lane appends
               this alternation to its KEEP regex.
  is_law_firm  a hint from the employer name, for a [LAW FIRM] tag in lane
               output. A hint only: "LLP" also covers accounting firms, and
               the exclusion list cannot be complete.
  LAW_JD       law-firm signals in JD text (legal-tech products, "law firm",
               "attorneys"), for lanes that read the JD body.

INVARIANTS
  * LAW_TITLES is a regex fragment with no outer flags, so a lane can join it
    to its own pattern with "|" and compile with re.I.
  * is_law_firm never raises on None or an empty name.
"""

import re

LAW_TITLES = (
    r"\b(?:litigation support|practice (?:support|technology|innovation analyst)|"
    r"legal (?:technology|tech|it|systems)|e-?discovery|"
    r"(?:technology|it|software|applications?) trainer|technology training|"
    r"technology (?:operations |support |services )?(?:specialist|support|analyst|associate|coordinator|technician)|"
    r"deskside support|desk-?side|application(?:s)? (?:support|specialist)|"
    r"information services|client technology|attorney support)\b"
)

_FIRM = re.compile(
    r"\bL\.?L\.?P\b|\bP\.?L\.?L\.?C\b|\blaw (?:firm|group|offices?|llp|llc|pc)\b|"
    r"\battorneys?\b|\blegal\b|"
    # Large firms whose names carry no legal word (KC office or remote IT hiring).
    r"polsinelli|husch blackwell|shook,? hardy|stinson|spencer fane|lathrop|kutak rock|"
    r"dentons|bryan cave|\bbclp\b|armstrong teasdale|ogletree|littler|jackson lewis|"
    r"fisher phillips|lewis rice|constangy|lewis brisbois|norton rose|kirkland|latham|"
    r"skadden|sidley|jones day|baker mckenzie|mcdermott|holland & knight|greenberg traurig|"
    r"morgan,? lewis|dla piper|faegre|perkins coie|k&l gates|seyfarth|foley|squire|"
    r"wilson sonsini|cooley|goodwin|orrick|ropes|crowell|nixon peabody|davis wright|"
    r"freeman mathis|wilson elser|gunderson|jenner|steptoe|allen matkins|miller johnson|"
    r"offit kurman|clyde & co|hogan lovells|white & case|winston & strawn|mayer brown|"
    r"quinn emanuel|paul hastings|proskauer|akin|alston & bird|bracewell|husch",
    re.I)

# LLP and PLLC also cover accountancies, clinics and architects.
_NOT_FIRM = re.compile(
    r"\bcpas?\b|accounting|accountants|audit|\btax\b|deloitte|kpmg|pwc|pricewaterhouse|"
    r"ernst|grant thornton|\bbdo\b|cliftonlarsonallen|\bcla\b|crowe|moss adams|plante moran|"
    r"baker tilly|rubinbrown|rsm\b|marcum|eisner|cohnreznick|wipfli|forvis|"
    r"clinic|urology|pediatric|medical|health|dental|eye|rheumatology|architects?|"
    r"enforcement|lawn|lawson|legalzoom|legalshield|thomson|lexis|wolters|clio|"
    r"filevine|intapp|imanage|epiq|consilio|integreon|unitedlex|staffing|recruit|"
    r"university|college|school|hospitality|motor|entertainment",
    re.I)

LAW_JD = re.compile(
    r"\b(?:law firm|attorneys|lawyers|legal professionals|billable|"
    r"imanage|netdocuments|elite 3e|\b3e\b|aderant|intapp|prolaw|worldox|"
    r"litigation support|ediscovery|e-discovery|relativity)\b", re.I)


def is_law_firm(company: str | None) -> bool:
    """True when the employer name looks like a law firm (a hint, not a fact)."""
    name = company or ""
    return bool(_FIRM.search(name)) and not _NOT_FIRM.search(name)


def tag(company: str | None, jd: str = "") -> str:
    """' [LAW FIRM]' for lane output, else ''."""
    if is_law_firm(company):
        return " [LAW FIRM]"
    if jd and len(LAW_JD.findall(jd)) >= 2:
        return " [LAW FIRM? JD]"
    return ""
