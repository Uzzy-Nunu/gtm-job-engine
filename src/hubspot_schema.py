"""The HubSpot data model for GTM Job Engine (PRD §9).

The free CRM allows 10 custom properties in total across the account, so the
model is deliberately lean (9 custom deal properties, 1 spare). Everything
else uses HubSpot's built-in fields, associations and notes:

| Information                         | Where it lives                                |
|-------------------------------------|-----------------------------------------------|
| Job title + company                 | Deal name: "<Job Title> - <Company>"          |
| Raw job / post text                 | Built-in deal "Deal description"              |
| Seniority, salary, regions, skills, | Custom `job_analysis` (one readable block)    |
|   tools, fit reasons, missing       |                                               |
|   keywords, suggested contact titles|                                               |
| "Needs post text" flag              | `pipeline_error` starting "NEEDS POST TEXT"   |
| Company brief                       | Built-in company "Description" + deal note    |
| CV and cover letter files           | Note attachments on the deal                  |
| Connection note, follow-up message  | "Drafts" note on the deal                     |
| Poster's LinkedIn profile           | Built-in contact "LinkedIn URL"               |
| LinkedIn post ID (duplicate key)    | Inside the canonical `job_url`                |

Other modules import names from here, so the model is defined once.
"""

PIPELINE_LABEL = "Job Applications"

# (label, probability). HubSpot treats probability 1.0 as Closed Won and
# 0.0 as Closed Lost.
STAGES = [
    ("New", 0.1),
    ("Qualified", 0.2),
    ("Researched", 0.3),
    ("Ready for Review", 0.4),
    ("Approved", 0.5),
    ("Applied", 0.6),
    ("Followed Up", 0.7),
    ("Interviewing", 0.8),
    ("Offer", 1.0),
    ("Rejected", 0.0),
    ("Archived", 0.0),
]

DEAL_PROPERTY_GROUP = {"name": "gtm_job_engine", "label": "GTM Job Engine"}

JOB_SOURCES = ["LinkedIn Post", "LinkedIn Alert", "Greenhouse", "Lever",
               "Ashby", "RemoteOK", "Himalayas", "WWR"]
REMOTE_SCOPES = ["Worldwide", "Region", "Country-restricted", "Unclear",
                 "Not remote"]

NEEDS_POST_TEXT = "NEEDS POST TEXT"


def _options(values):
    return [{"label": v, "value": v, "displayOrder": i}
            for i, v in enumerate(values)]


# Each entry is the exact body sent to POST /crm/v3/properties/deals.
DEAL_PROPERTIES = [
    {"name": "job_url", "label": "Job URL", "type": "string",
     "fieldType": "text", "hasUniqueValue": True,
     "description": "Normalised job or LinkedIn post URL. Unique key for "
                    "duplicate checks."},
    {"name": "job_source", "label": "Job Source", "type": "enumeration",
     "fieldType": "select", "options": _options(JOB_SOURCES)},
    {"name": "apply_url", "label": "Apply URL", "type": "string",
     "fieldType": "text"},
    {"name": "remote_scope", "label": "Remote Scope", "type": "enumeration",
     "fieldType": "select", "options": _options(REMOTE_SCOPES)},
    {"name": "fit_score", "label": "Fit Score", "type": "number",
     "fieldType": "number", "description": "0-100, see PRD §11.3."},
    {"name": "keyword_coverage", "label": "Keyword Coverage %",
     "type": "number", "fieldType": "number"},
    {"name": "job_analysis", "label": "Job Analysis", "type": "string",
     "fieldType": "textarea",
     "description": "Fit reasons, seniority, salary, eligible regions, "
                    "skills, tools, missing keywords and suggested contact "
                    "titles."},
    {"name": "pipeline_error", "label": "Pipeline Error", "type": "string",
     "fieldType": "textarea",
     "description": "Set by the system when something needs a human. "
                    "'NEEDS POST TEXT' means paste the post text into Deal "
                    "description."},
    {"name": "applied_date", "label": "Applied Date", "type": "date",
     "fieldType": "date"},
]

for _p in DEAL_PROPERTIES:
    _p["groupName"] = DEAL_PROPERTY_GROUP["name"]

# Built-in contact property used for the poster's LinkedIn profile link.
CONTACT_LINKEDIN_PROPERTY = "hs_linkedin_url"

# Objects whose custom properties count toward the free-plan limit.
COUNTED_OBJECTS = ["deals", "contacts", "companies"]
