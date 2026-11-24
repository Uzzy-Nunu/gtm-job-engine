"""The master CV as numbered, checkable pieces (PRD §12, CLAUDE.md rule 4).

The AI never writes employers, dates or titles. It picks numbered bullets
(r1b2, p1b1, ...) and rewords them; this module turns those picks into a CV
using the real employers, dates and titles from the master CV, and rejects
anything that doesn't trace back to it:
  - unknown or [CONFIRM] bullets are dropped
  - titles must be the real title or a listed title variant
  - skills and tools must appear in the master CV
  - roles stay in master order (newest first)

Parsing follows the master CV's own layout:
  ### Title                                  ### Employer (one employer, progression)
  Company | Location | Dates                 Location | Dates
  Title variants: "A" | "B"                  #### Sub-role title | Dates
  Context: ...                               - bullet [TAG]
  - bullet [TAG][TAG]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.cv_sections import sections
from src.redact import redact

# Web addresses (project live links etc.): the AI doesn't need them.
WEB_ADDRESS = re.compile(
    r"(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:app|com|io|ai|co|dev|net|org|me|site|xyz)\b(?:/\S*)?",
    re.IGNORECASE)

TAGS = re.compile(r"((?:\s*\[[A-Z][A-Z0-9 :,&/'-]*\])+)\s*$")


@dataclass
class Bullet:
    id: str
    text: str
    tags: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return "CONFIRM" not in self.tags


@dataclass
class Role:
    id: str
    title: str
    company: str
    location: str = ""
    dates: str = ""
    variants: list[str] = field(default_factory=list)
    optional: str | None = None     # None, or the condition text ("agency, brand or content roles only")
    context: str = ""
    bullets: list[Bullet] = field(default_factory=list)


@dataclass
class Project:
    id: str
    name: str
    details: str = ""
    bullets: list[Bullet] = field(default_factory=list)


@dataclass
class Certification:
    id: str
    text: str
    optional: str | None = None


@dataclass
class MasterCV:
    contact: dict[str, str]
    target_titles: list[str]
    headline_options: list[str]
    summaries: dict[str, str]
    skills: dict[str, list[str]]
    tools: dict[str, list[str]]
    roles: list[Role]
    projects: list[Project]
    education: list[str]
    certifications: list[Certification]
    languages: str
    evidence: str
    rules: str

    def all_skills(self) -> list[str]:
        return [s for items in self.skills.values() for s in items]

    def all_tools(self) -> list[str]:
        return [t for items in self.tools.values() for t in items]

    def role(self, role_id: str) -> Role | None:
        return next((r for r in self.roles if r.id == role_id), None)

    def project(self, project_id: str) -> Project | None:
        return next((p for p in self.projects if p.id == project_id), None)


# --- parsing --------------------------------------------------------------------

def _section(parts: dict[str, str], prefix: str) -> str:
    return next((body for heading, body in parts.items() if heading.startswith(prefix)), "")


def _lines(body: str) -> list[str]:
    return [l.rstrip() for l in body.splitlines()]


def _split_tags(text: str) -> tuple[str, list[str]]:
    match = TAGS.search(text)
    if not match:
        return text.strip(), []
    tags = re.findall(r"\[([^\]]+)\]", match.group(1))
    return text[:match.start()].strip(), [t.split(":")[0].strip() for t in tags]


def _optional(heading: str) -> tuple[str, str | None]:
    match = re.search(r"\[OPTIONAL(?::\s*([^\]]*))?\]", heading)
    if not match:
        return heading.strip(), None
    return heading[:match.start()].strip(), (match.group(1) or "relevant roles only").strip()


def _dates(text: str) -> str:
    return re.sub(r"\s*[-–—]\s*", " - ", text.strip())


def _items(body: str) -> dict[str, list[str]]:
    """'Group: a, b (c, d), e' lines -> {group: [a, b (c, d), e]} (commas inside brackets kept)."""
    groups: dict[str, list[str]] = {}
    for line in _lines(body):
        line = line.strip()
        if not line or line.startswith(("[", "(", "#")) or ":" not in line:
            continue
        label, rest = line.split(":", 1)
        items, depth, current = [], 0, ""
        for ch in rest:
            depth += ch == "("
            depth -= ch == ")"
            if ch == "," and depth == 0:
                items.append(current.strip())
                current = ""
            else:
                current += ch
        items.append(current.strip())
        groups[label.strip()] = [i for i in items if i]
    return groups


def _parse_roles(body: str) -> list[Role]:
    roles: list[Role] = []
    parent: Role | None = None      # an employer heading whose roles follow as ####
    current: Role | None = None
    awaiting_header = False         # the line after "### ..." holds company | location | dates
    n = 0
    for raw in _lines(body):
        line = raw.strip()
        if line.startswith("#### ") and parent is not None:
            title, _, dates = line[5:].partition("|")
            count = sum(1 for r in roles if r.id.startswith(parent.id) and r.id != parent.id)
            current = Role(id=f"{parent.id}{chr(ord('a') + count)}", title=title.strip(),
                           company=parent.company, location=parent.location,
                           dates=_dates(dates) if dates.strip() else parent.dates)
            roles.append(current)
            awaiting_header = False
        elif line.startswith("### "):
            n += 1
            heading, optional = _optional(line[4:])
            current = Role(id=f"r{n}", title=heading, company="", optional=optional)
            roles.append(current)
            parent, awaiting_header = None, True
        elif current is None or not line:
            continue
        elif awaiting_header and "|" in line and not line.startswith("-"):
            awaiting_header = False
            parts = [part.strip() for part in line.split("|")]
            if len(parts) >= 3:
                current.company, current.location, current.dates = parts[0], parts[1], _dates(parts[-1])
            else:  # "Location | Dates": the heading names the employer
                current.company = re.sub(r"\s*\(.*\)\s*$", "", current.title).strip()
                current.location, current.dates, current.title = parts[0], _dates(parts[-1]), ""
                parent = current
        elif line.lower().startswith("title variants:"):
            current.variants = [v.strip().strip('"').strip() for v in line.split(":", 1)[1].split("|") if v.strip()]
        elif line.lower().startswith("context:"):
            current.context = line.split(":", 1)[1].strip()
        elif line.startswith("- "):
            text, tags = _split_tags(line[2:])
            current.bullets.append(Bullet(f"{current.id}b{len(current.bullets) + 1}", text, tags))
    # An employer heading with sub-roles isn't a role itself.
    return [r for r in roles if r.title or r.bullets]


def _parse_projects(body: str) -> list[Project]:
    projects: list[Project] = []
    for raw in _lines(body):
        line = raw.strip()
        if line.startswith("### "):
            projects.append(Project(id=f"p{len(projects) + 1}", name=line[4:].strip()))
        elif projects and line.startswith("- "):
            text, tags = _split_tags(line[2:])
            p = projects[-1]
            p.bullets.append(Bullet(f"{p.id}b{len(p.bullets) + 1}", text, tags))
        elif projects and line and not line.startswith(("[", "(")) and not projects[-1].bullets:
            projects[-1].details = (projects[-1].details + " " + line).strip()
    return projects


def _parse_certifications(body: str) -> list[Certification]:
    certs = []
    for raw in _lines(body):
        line = raw.strip()
        if line.startswith("- "):
            without_flag, optional = _optional(line[2:])
            text, _ = _split_tags(without_flag)
            certs.append(Certification(f"c{len(certs) + 1}", text, optional))
    return certs


def _parse_summaries(body: str) -> dict[str, str]:
    found, key = {}, None
    for raw in _lines(body):
        line = raw.strip()
        m = re.fullmatch(r"\[([A-Z][A-Z0-9 /'-]*)\]", line)
        if m:
            key = m.group(1)
            found[key] = ""
        elif key and line:
            found[key] = (found[key] + " " + line).strip()
    return found


def parse_master_cv(text: str) -> MasterCV:
    parts = sections(text)
    contact = {}
    for line in _lines(_section(parts, "CONTACT")):
        if ":" in line and not line.strip().startswith("#"):
            key, value = line.split(":", 1)
            contact[key.strip().lower()] = value.strip()
    titles = []
    for line in _lines(_section(parts, "TARGET TITLES")):
        if ":" in line:
            titles += [t.strip() for t in line.split(":", 1)[1].split("|") if t.strip()]
    headline = [l.strip()[2:].strip() for l in _lines(_section(parts, "HEADLINE")) if l.strip().startswith("- ")]
    edu = [l.strip() for l in _lines(_section(parts, "EDUCATION")) if l.strip()]
    lang = " ".join(l.strip() for l in _lines(_section(parts, "LANGUAGES")) if l.strip())
    return MasterCV(
        contact=contact, target_titles=titles, headline_options=headline,
        summaries=_parse_summaries(_section(parts, "SUMMARY")),
        skills=_items(_section(parts, "CORE SKILLS")), tools=_items(_section(parts, "TOOLS")),
        roles=_parse_roles(_section(parts, "PROFESSIONAL EXPERIENCE")),
        projects=_parse_projects(_section(parts, "PROJECTS")),
        education=edu, certifications=_parse_certifications(_section(parts, "CERTIFICATIONS")),
        languages=lang, evidence=_section(parts, "EVIDENCE BANK"), rules=_section(parts, "RULES"),
    )


# --- what the AI sees (never the contact block) ----------------------------------

def for_ai(cv: MasterCV) -> str:
    out = ["TARGET TITLES: " + " | ".join(cv.target_titles)]
    if cv.headline_options:
        out.append("HEADLINE KEYWORD OPTIONS: " + " || ".join(cv.headline_options))
    out.append("\nSUMMARY VARIANTS:")
    out += [f"[{k}] {v}" for k, v in cv.summaries.items()]
    out.append("\nCORE SKILLS (use these exact items):")
    out += [f"- {g}: {', '.join(items)}" for g, items in cv.skills.items()]
    out.append("\nTOOLS (use these exact items):")
    out += [f"- {g}: {', '.join(items)}" for g, items in cv.tools.items()]
    out.append("\nROLES (newest first; ids in brackets):")
    for r in cv.roles:
        flag = f" [OPTIONAL: {r.optional}]" if r.optional else ""
        variants = f" | allowed title variants: {' / '.join(r.variants)}" if r.variants else ""
        out.append(f"[{r.id}] {r.title} at {r.company} ({r.dates}){flag}{variants}")
        if r.context:
            out.append(f"    context: {r.context}")
        for b in r.bullets:
            if b.usable:
                out.append(f"    [{b.id}] {b.text}" + (f"  {{{', '.join(b.tags)}}}" if b.tags else ""))
    out.append("\nPROJECTS:")
    for p in cv.projects:
        out.append(f"[{p.id}] {p.name}" + (f" ({p.details})" if p.details else ""))
        out += [f"    [{b.id}] {b.text}" for b in p.bullets if b.usable]
    out.append("\nCERTIFICATIONS:")
    out += [f"[{c.id}] {c.text}" + (f" [OPTIONAL: {c.optional}]" if c.optional else "") for c in cv.certifications]
    view = WEB_ADDRESS.sub("[link removed]", "\n".join(out))
    return redact(view)  # second safety net: no emails, phones or profile links


def experience_overview(cv: MasterCV) -> str:
    """What the Qualify step needs to judge seniority and real experience:
    role titles with dates, their usable bullets, projects and certifications.
    Employer names are left out (not needed to score fit). Redacted."""
    out = ["PROFESSIONAL EXPERIENCE (newest first; employer names left out):"]
    for r in cv.roles:
        out.append(f"- {r.title} ({r.dates})")
        out += [f"    - {b.text}" for b in r.bullets if b.usable]
    if cv.projects:
        out.append("\nPROJECTS:")
        for p in cv.projects:
            out.append(f"- {p.name}")
            out += [f"    - {b.text}" for b in p.bullets if b.usable]
    if cv.certifications:
        out.append("\nCERTIFICATIONS:")
        out += [f"- {c.text}" for c in cv.certifications]
    view = WEB_ADDRESS.sub("[link removed]", "\n".join(out))
    return redact(view)


# --- turning AI picks into a checked CV ----------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _in_master(item: str, master_items: list[str]) -> str | None:
    """The master item this pick refers to, matching whole words only, so
    "SQL" never matches "PostgreSQL". A shorter pick inside a master item
    keeps the pick's wording; a longer pick falls back to the master item."""
    n = _norm(item)
    if not n:
        return None
    for m in master_items:
        if _norm(m) == n:
            return m
    for m in master_items:
        nm = _norm(m)
        if f" {n} " in f" {nm} ":
            return item
        if f" {nm} " in f" {n} " and len(nm) >= 4:
            return m
    return None


@dataclass
class Assembled:
    cv: dict
    problems: list[str]
    used_bullets: dict[str, str]   # source id -> AI wording (for the truth check)


MAX_BULLETS = 5


def assemble(master: MasterCV, picks: dict) -> Assembled:
    problems: list[str] = []
    used: dict[str, str] = {}

    headline = (picks.get("headline") or "").strip()
    allowed_heads = master.target_titles + [v for r in master.roles for v in r.variants]
    if not any(_norm(t) and _norm(t) in _norm(headline) for t in allowed_heads):
        problems.append(f"Headline '{headline}' isn't one of your target titles; used '{master.target_titles[0]}'.")
        headline = master.target_titles[0] if master.target_titles else ""

    def take(items, master_items, label):
        kept = []
        for item in items or []:
            match = _in_master(item, master_items)
            if match and match not in kept:
                kept.append(match)
            elif not match:
                problems.append(f"Dropped {label} not in your master CV: '{item}'.")
        return kept

    skills = take(picks.get("core_skills"), master.all_skills(), "skill")
    tools = take(picks.get("tools"), master.all_tools(), "tool")

    chosen_roles = {}
    for pick in picks.get("roles") or []:
        role = master.role(pick.get("role_id", ""))
        if role is None:
            problems.append(f"Dropped unknown role '{pick.get('role_id')}'.")
            continue
        title = (pick.get("title") or role.title).strip()
        if _norm(title) not in [_norm(role.title)] + [_norm(v) for v in role.variants]:
            problems.append(f"Title '{title}' isn't your real title for {role.company}; used '{role.title}'.")
            title = role.title
        bullets = []
        for b in pick.get("bullets") or []:
            source = next((x for x in role.bullets if x.id == b.get("source_id")), None)
            text = (b.get("text") or "").strip()
            if source is None:
                problems.append(f"Dropped a bullet with unknown source '{b.get('source_id')}' in {role.company}.")
            elif not source.usable:
                problems.append(f"Dropped bullet {source.id}: marked [CONFIRM] in your master CV.")
            elif text:
                bullets.append(text)
                used[source.id] = text
        if len(bullets) > MAX_BULLETS:
            problems.append(f"Kept the first {MAX_BULLETS} bullets for {role.company}.")
            bullets = bullets[:MAX_BULLETS]
        if not bullets and role.bullets:
            problems.append(f"Role {role.id} had no usable bullets and was left out.")
            continue
        chosen_roles[role.id] = {"title": title, "company": role.company, "dates": role.dates, "bullets": bullets}
    experience = [chosen_roles[r.id] for r in master.roles if r.id in chosen_roles]

    projects = []
    for pick in picks.get("projects") or []:
        project = master.project(pick.get("project_id", ""))
        if project is None:
            problems.append(f"Dropped unknown project '{pick.get('project_id')}'.")
            continue
        bullets = []
        for b in pick.get("bullets") or []:
            source = next((x for x in project.bullets if x.id == b.get("source_id")), None)
            if source is None or not source.usable:
                problems.append(f"Dropped a project bullet with unknown or unconfirmed source '{b.get('source_id')}'.")
            elif (b.get("text") or "").strip():
                bullets.append(b["text"].strip())
                used[source.id] = b["text"].strip()
        projects.append({"name": project.name, "bullets": bullets})

    certs = []
    for cid in picks.get("certification_ids") or []:
        cert = next((c for c in master.certifications if c.id == cid), None)
        if cert:
            certs.append(cert.text)
        else:
            problems.append(f"Dropped unknown certification '{cid}'.")

    cv = {
        "name": master.contact.get("name", ""),
        "headline": headline,
        "contact": {k: master.contact.get(k) for k in ("email", "linkedin", "portfolio") if master.contact.get(k)},
        "summary": (picks.get("summary") or "").strip(),
        "core_skills": skills,
        "tools": tools,
        "experience": experience,
        "projects": projects,
        "education": master.education,
        "certifications": certs,
        "languages": [master.languages] if master.languages else [],
    }
    return Assembled(cv, problems, used)


def master_text_for(master: MasterCV, source_ids) -> dict[str, str]:
    """Original master wording for the given bullet ids (for the truth check)."""
    every = {b.id: b.text for r in master.roles for b in r.bullets}
    every.update({b.id: b.text for p in master.projects for b in p.bullets})
    return {i: every[i] for i in source_ids if i in every}


# --- two pages maximum (PRD §12) ---------------------------------------------------

CHARS_PER_LINE = 105   # A4, 10.5pt, the template's margins
MAX_LINES = 2 * 58


def estimate_lines(cv: dict) -> int:
    def lines(text: str) -> int:
        return max(1, -(-len(text) // CHARS_PER_LINE))
    total = 3 + (1 if cv.get("headline") else 0)
    total += 2 + lines(cv.get("summary", "")) if cv.get("summary") else 0
    for key in ("core_skills", "tools", "languages"):
        if cv.get(key):
            total += 2 + lines(", ".join(cv[key]))
    for role in cv.get("experience", []):
        total += 2 + sum(lines("- " + b) for b in role["bullets"])
    for project in cv.get("projects", []):
        total += 1 + sum(lines("- " + b) for b in project["bullets"])
    total += 2 + len(cv.get("education", [])) + len(cv.get("certifications", []))
    return total + 8   # section headings and spacing


def fit_two_pages(cv: dict, problems: list[str]) -> dict:
    """Trim bullets, oldest roles first (keeping one per role), then project
    bullets, until the CV fits two pages."""
    trimmed = 0
    while estimate_lines(cv) > MAX_LINES:
        role = next((r for r in reversed(cv.get("experience", [])) if len(r["bullets"]) > 1), None)
        if role:
            role["bullets"].pop()
        else:
            project = next((p for p in reversed(cv.get("projects", [])) if p["bullets"]), None)
            if not project:
                break
            project["bullets"].pop()
        trimmed += 1
    if trimmed:
        problems.append(f"Trimmed {trimmed} bullet(s) from older roles to fit two pages.")
    return cv
