"""Check the AI connection and the master CV secret, before real jobs are processed.

- Sends ONE tiny request with made-up text to the configured model and checks
  the answer comes back as valid JSON.
- Checks the master CV can be read and split into the sections the Qualify
  step uses. Prints only section names and sizes, never content (GitHub
  Actions logs on a public repo are public).

Usage:  python scripts/check_ai.py      (needs LLM_API_KEY; MASTER_CV or MASTER_CV_PATH)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.hubspot_client import load_dotenv  # noqa: E402
from src.llm import LLMError, make_llm  # noqa: E402
from src.cv_sections import (QUALIFY_SECTIONS, MasterCVError, load_text,  # noqa: E402
                           qualify_profile, sections)

SCHEMA = {
    "type": "object",
    "required": ["remote_scope", "title"],
    "properties": {
        "remote_scope": {"type": "string", "enum": ["Worldwide", "Region", "Country-restricted", "Unclear", "Not remote"]},
        "title": {"type": "string"},
    },
}
SAMPLE = "SampleCorp is hiring a GTM Engineer. Fully remote, open to candidates anywhere in the world."


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    ok = True

    print("== AI connection")
    try:
        llm = make_llm(config)
        start = time.monotonic()
        answer = llm.generate_json(
            system="You extract job facts. Answer only from the text.",
            prompt=f"Job text:\n{SAMPLE}\n\nReturn the job title and remote scope.",
            schema=SCHEMA, role="fast")
        print(f"  provider: {llm.name} | model: {llm.models.get('fast')} | "
              f"{time.monotonic() - start:.1f}s | requests: {llm.calls}")
        print(f"  answer: {answer}")
        if answer.get("remote_scope") != "Worldwide":
            print("  ! The answer is valid JSON, but the remote scope looks wrong. Check the model choice.")
        else:
            print("  OK: the AI answered correctly in the expected format.")
    except LLMError as e:
        ok = False
        print(f"  FAILED: {e}")

    print("\n== Master CV")
    try:
        text = load_text()
        found = sections(text)
        print(f"  read OK: {len(text):,} characters, {len(found)} sections")
        for wanted in QUALIFY_SECTIONS:
            match = next((h for h in found if h.startswith(wanted)), None)
            print(f"  {'OK  ' if match else 'MISSING'} {wanted}")
            ok = ok and bool(match)
        profile = qualify_profile(text)
        print(f"  Qualify step will send {len(profile):,} characters (skills, tools, target titles; no contact details)")
    except MasterCVError as e:
        ok = False
        print(f"  FAILED: {e}")

    print("\nAll checks passed." if ok else "\nSome checks failed (see above).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
