"""Hard filters and the fit-score rubric (PRD §10.2 QU-2..QU-4, §11.3).

The AI only reports facts and an overlap judgement; every rule and every point
here is applied by code, so scores are consistent and explainable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.job_filter import TitleFilter, _contains_phrase, _norm, region_ok


AI_OVERLAP_SCALE = 20      # skills_overlap_points in the Qualify schema is 0-20


@dataclass
class Verdict:
    score: int
    qualified: bool
    archive_reason: str | None = None
    breakdown: list[tuple[str, int]] = field(default_factory=list)
    note: str | None = None


def hard_filter(facts: dict, config: dict) -> str | None:
    """Reason to archive without scoring, or None (PRD QU-2)."""
    scope = facts.get("remote_scope")
    regions = facts.get("eligible_regions") or ""
    eligible = config.get("eligible_regions") or []
    if scope == "Not remote":
        return "Not remote (on-site or hybrid)."
    if scope in ("Country-restricted", "Region") and regions and not region_ok(regions, eligible):
        return f"Remote only for {regions}, which isn't open to you."
    title = _norm(facts.get("job_title") or "")
    hit = next((w for w in config.get("excluded_title_words") or [] if _contains_phrase(title, w)), None)
    if hit:
        return f"Title contains the excluded word '{hit}'."
    return None


def score(facts: dict, config: dict, hand_picked: bool = False) -> Verdict:
    """Hard filters, then the rubric. Hand-picked jobs (captured by Peace)
    skip the score threshold but never the hard filters (decision 18 Nov 2026)."""
    rubric = config.get("rubric") or {}
    threshold = int(config.get("fit_threshold", 70))
    reason = hard_filter(facts, config)
    if reason:
        return Verdict(0, False, reason, [("Hard filter", 0)])

    parts: list[tuple[str, int]] = []

    remote = rubric.get("remote", {})
    scope = facts.get("remote_scope")
    if scope == "Worldwide":
        parts.append(("Remote worldwide", remote.get("worldwide", 30)))
    elif scope in ("Region", "Country-restricted"):
        parts.append((f"Remote in an eligible region ({facts.get('eligible_regions')})",
                      remote.get("eligible_region", 20)))
    else:
        parts.append(("Remote scope unclear", remote.get("unclear", 10)))

    titles = rubric.get("title", {})
    match = TitleFilter.from_config(config).match(facts.get("job_title") or "")
    title_points = {"target": titles.get("target_match", 25), "adjacent": titles.get("adjacent_match", 15),
                    "explore": titles.get("explore_match", 10)}.get(match, 0)
    parts.append((f"Title {'matches your ' + match + ' list' if match else 'not on your lists'}", title_points))

    # The AI judges overlap on a 0-20 scale; the rubric decides what it's worth.
    cap = int(rubric.get("skills_tools_overlap_max", 20))
    overlap = max(0, min(AI_OVERLAP_SCALE, int(facts.get("skills_overlap_points") or 0)))
    parts.append((f"Skills and tools overlap ({overlap}/{AI_OVERLAP_SCALE})", round(overlap * cap / AI_OVERLAP_SCALE)))

    sen = rubric.get("seniority", {})
    level = facts.get("seniority") or "Unclear"
    if level in sen.get("preferred", ["Entry", "Mid"]):
        sen_points = sen.get("points", 15)
    elif level in sen.get("allowed_if_requirements_match", ["Senior"]) and facts.get("senior_requirements_met"):
        sen_points = sen.get("points", 15)
    elif level in sen.get("allowed_if_requirements_match", ["Senior"]):
        sen_points = sen.get("senior_partial_points", 0)   # close, but not a full match
        level = f"{level}, requirements not fully met"
    elif level == "Unclear":
        sen_points = sen.get("unclear_points", 7)
    else:
        sen_points = 0
    parts.append((f"Seniority: {level}", sen_points))

    salary_points = int(rubric.get("salary_listed", 10))
    if salary_points:
        parts.append(("Salary listed" if facts.get("salary_text") else "No salary listed",
                      salary_points if facts.get("salary_text") else 0))

    total = min(100, sum(p for _, p in parts))
    if total >= threshold:
        return Verdict(total, True, None, parts)
    if hand_picked:
        return Verdict(total, True, None, parts,
                       note=f"Hand-picked by you: kept although the score is below {threshold}.")
    return Verdict(total, False, f"Fit score {total} is below the threshold of {threshold}.", parts)


def analysis_text(facts: dict, verdict: Verdict, threshold: int) -> str:
    """The readable Job Analysis block stored on the deal."""
    status = "Qualified" if verdict.qualified else "Archived"
    lines = [f"Fit score: {verdict.score}/100 (threshold {threshold}) -> {status}"]
    if verdict.archive_reason:
        lines.append(f"Reason: {verdict.archive_reason}")
    if verdict.note:
        lines.append(f"Note: {verdict.note}")
    lines.append("Score: " + " | ".join(f"{label} +{points}" for label, points in verdict.breakdown))
    if facts.get("fit_reasons"):
        lines.append("Why:")
        lines += [f"- {r}" for r in facts["fit_reasons"]]
    lines.append(f"Seniority: {facts.get('seniority') or 'Unclear'} | "
                 f"Salary: {facts.get('salary_text') or 'not listed'} | "
                 f"Remote: {facts.get('remote_scope')} ({facts.get('eligible_regions') or 'no limits stated'})")
    for label, key in (("Required skills", "required_skills"), ("Tools mentioned", "tools_mentioned"),
                       ("Matched from your CV", "matched_skills"),
                       ("Gaps (don't add these to your CV unless true)", "missing_requirements")):
        if facts.get(key):
            lines.append(f"{label}: {', '.join(facts[key])}")
    return "\n".join(lines)
