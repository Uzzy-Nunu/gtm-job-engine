"""URL helpers for intake (PRD §10.1 IN-1c, IN-2, IN-4).

Everything here works on the URL *text* only. Nothing is fetched, and
LinkedIn is never contacted (CLAUDE.md rule 2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only track clicks and never identify a job.
TRACKING_PARAMS = {
    "ref", "refid", "referrer", "source", "src", "trk", "trkinfo", "trackingid",
    "gh_src", "gh_jid_src", "lever-source", "lever-origin", "lever-via",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "rcm", "lipi", "originalsubdomain",
}
TRACKING_PREFIXES = ("utm_",)

LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com", "m.linkedin.com", "lnkd.in"}

_POST_ID = re.compile(r"-(activity|ugcPost|share)-(\d{15,25})", re.IGNORECASE)
_URN = re.compile(r"urn:li:(activity|ugcPost|share):(\d{15,25})", re.IGNORECASE)
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


class URLError(ValueError):
    """The URL can't be used. The message is shown to Peace as-is."""


@dataclass(frozen=True)
class LinkedInPost:
    post_id: str
    urn_type: str                  # activity | ugcPost | share
    canonical_url: str             # duplicate-check key, stored in job_url
    author_slug: str | None = None
    profile_url: str | None = None
    name_guess: str | None = None  # best guess, always shown as unconfirmed


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_linkedin(url: str) -> bool:
    host = _host(url)
    return host in LINKEDIN_HOSTS or host.endswith(".linkedin.com")


_LINKEDIN_JOB = re.compile(r"/(?:comm/)?jobs/view/(?:[^/?#]*?-)?(\d{6,})", re.IGNORECASE)


def linkedin_job_url(url: str) -> str | None:
    """Canonical https://www.linkedin.com/jobs/view/<id> for a LinkedIn job link
    (as found in job-alert emails), or None. Used only as a duplicate key and a
    link for Peace: the system never opens it."""
    if not is_linkedin(url):
        return None
    m = _LINKEDIN_JOB.search(urlsplit(_clean_input(url)).path)
    return f"https://www.linkedin.com/jobs/view/{m.group(1)}" if m else None


def _clean_input(url: str) -> str:
    url = (url or "").strip().strip("<>\"'")
    if not url:
        raise URLError("Please paste a link.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    if not _host(url) or "." not in _host(url):
        raise URLError(f"That doesn't look like a web link: {url}")
    return url


def normalise_url(url: str) -> str:
    """Canonical form used for duplicate checks: https, lowercase host,
    no 'www.', no tracking parameters, no #fragment, no trailing slash."""
    url = _clean_input(url)
    if is_linkedin(url):
        job = linkedin_job_url(url)
        if job:
            return job
        post = parse_linkedin_post(url)
        return post.canonical_url
    parts = urlsplit(url)
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if k.lower() not in TRACKING_PARAMS
             and not k.lower().startswith(TRACKING_PREFIXES)]
    query.sort()
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/")
    return urlunsplit(("https", host, path, urlencode(query), ""))


def _name_from_slug(slug: str) -> str | None:
    """'jane-doe-123' -> 'Jane Doe'. Drops trailing parts that contain digits
    (LinkedIn adds them to make vanity names unique)."""
    words = [w for w in slug.split("-") if w]
    while words and re.search(r"\d", words[-1]):
        words.pop()
    words = [w for w in words if not re.search(r"\d", w)]
    if not words:
        return None
    return " ".join(w.capitalize() for w in words)


def parse_linkedin_post(url: str) -> LinkedInPost:
    """Read the post ID (and author, when present) from a LinkedIn post URL.

    Supported:
      linkedin.com/posts/<author-slug>_<words>-activity-<id>-<code>
      linkedin.com/posts/<author-slug>_<words>-ugcPost-<id>-<code>
      linkedin.com/feed/update/urn:li:activity:<id>   (no author)
    """
    url = _clean_input(url)
    host = _host(url)
    if host == "lnkd.in":
        raise URLError("Short lnkd.in links can't be read without visiting LinkedIn. "
                       "In the LinkedIn app, use '...' > 'Copy link to post' instead.")
    if not is_linkedin(url):
        raise URLError("This is not a LinkedIn link.")

    path = urlsplit(url).path
    author_slug = None
    match = None

    posts = re.search(r"/posts/([^/?#]+)", path)
    if posts:
        segment = posts.group(1)
        match = _POST_ID.search(segment)
        if "_" in segment:
            candidate = segment.split("_", 1)[0].lower()
            if re.fullmatch(r"[a-z0-9-]{2,100}", candidate):
                author_slug = candidate
    else:
        match = _URN.search(path) or _URN.search(url)

    if not match:
        if "/jobs/" in path:
            raise URLError("LinkedIn job pages aren't supported (we never open LinkedIn). "
                           "Paste the hiring post link, or the job's link on the company site.")
        raise URLError("Couldn't find a post ID in this LinkedIn link. "
                       "Use '...' > 'Copy link to post' on the post.")

    urn_type = {"activity": "activity", "ugcpost": "ugcPost", "share": "share"}[match.group(1).lower()]
    post_id = match.group(2)
    canonical = f"https://www.linkedin.com/feed/update/urn:li:{urn_type}:{post_id}"
    profile = f"https://www.linkedin.com/in/{author_slug}" if author_slug else None
    return LinkedInPost(
        post_id=post_id,
        urn_type=urn_type,
        canonical_url=canonical,
        author_slug=author_slug,
        profile_url=profile,
        name_guess=_name_from_slug(author_slug) if author_slug else None,
    )


def find_external_job_links(text: str) -> list[str]:
    """Job links in post text that are NOT on LinkedIn (PRD IN-1e).
    Returned normalised, in order, without duplicates."""
    found = []
    for raw in _URL_IN_TEXT.findall(text or ""):
        raw = raw.rstrip(".,;:!?")
        try:
            if is_linkedin(raw):
                continue
            url = normalise_url(raw)
        except URLError:
            continue
        if url not in found:
            found.append(url)
    return found


def company_domain(url: str) -> str | None:
    """Best-effort company domain from a job URL. ATS hosts (Greenhouse,
    Lever, Ashby, Workable...) don't reveal the company's own domain."""
    host = _host(normalise_url(url))
    if host.startswith("www."):
        host = host[4:]
    ats = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
           "smartrecruiters.com", "bamboohr.com", "recruitee.com",
           "breezy.hr", "teamtailor.com", "personio.de", "personio.com",
           "remoteok.com", "himalayas.app", "weworkremotely.com", "wellfound.com",
           "remotive.com", "jobicy.com")
    if any(host == a or host.endswith("." + a) for a in ats):
        return None
    for prefix in ("jobs.", "careers.", "apply.", "boards."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host or None
