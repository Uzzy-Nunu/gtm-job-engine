"""Redaction tests: contact details never reach the AI (made-up data only)."""

import pytest

from src.redact import redact

JOB = """We're hiring a GTM Engineer at SampleCorp (fully remote, worldwide).
Salary: $70,000 - $90,000. Founded 2019, team of 45. Ref ID 7390000000000000001.
Apply: https://boards.greenhouse.io/samplecorp/jobs/123
Questions? Email jane.doe@samplecorp.example or call +1 (415) 555-0134.
WhatsApp +234 803 123 4567. DM me: https://www.linkedin.com/in/jane-doe-123
Also on x.com/janedoe and github.com/jdoe. Book a chat: calendly.com/jane/30min

--- Notes from Peace ---
Referred by my friend Ada, her number is 0803 555 1234"""


@pytest.fixture(scope="module")
def cleaned():
    return redact(JOB)


@pytest.mark.parametrize("secret", [
    "jane.doe@samplecorp.example", "415", "555-0134", "803 123 4567",
    "linkedin.com/in/jane-doe-123", "x.com/janedoe", "github.com/jdoe", "calendly.com/jane",
    "Notes from Peace", "Ada", "0803 555 1234",
])
def test_contact_details_are_removed(cleaned, secret):
    assert secret not in cleaned


@pytest.mark.parametrize("kept", [
    "GTM Engineer", "SampleCorp", "fully remote, worldwide",
    "$70,000 - $90,000", "Founded 2019", "team of 45",
    "https://boards.greenhouse.io/samplecorp/jobs/123",   # job links stay for research
    "7390000000000000001",                                # long IDs aren't phones
])
def test_useful_job_details_are_kept(cleaned, kept):
    assert kept in cleaned


def test_placeholders_show_what_was_removed(cleaned):
    assert "[email removed]" in cleaned
    assert "[phone removed]" in cleaned
    assert "[profile link removed]" in cleaned


def test_year_ranges_and_plain_text_survive():
    assert redact("Experience 2019-2023 with HubSpot") == "Experience 2019-2023 with HubSpot"
    assert redact("") == ""
