"""Real end-to-end smoke test of ResearchService against live InPASS portal."""

import json
import logging
import sys

# Ensure immediate line-buffered stdout
sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from pathlib import Path
import shutil
from src.common.research_runs import ResearchRunService
from src.patents.repository import PatentRepository
from src.patents.run_reader import ResearchRunPatentReader
from src.research.research_service import ResearchService

ARTIFACT_DIR = Path(r"C:\Users\gowth\.gemini\antigravity-ide\brain\a9ffa234-818f-4260-a870-f0bf1ac3b53e")


def solve_captcha(image_path: str) -> str:
    print(f"\n[CAPTCHA CAPTURED] Raw Image: {image_path}", flush=True)
    artifact_captcha = ARTIFACT_DIR / "inpass_captcha.png"
    try:
        shutil.copyfile(image_path, artifact_captcha)
        print(f"[CAPTCHA EXPOSED] Artifact Image: {artifact_captcha}", flush=True)
    except Exception as e:
        print(f"[Warning] Failed to copy artifact image: {e}", flush=True)

    print("\n>>> WAITING_FOR_CAPTCHA_INPUT <<<", flush=True)
    sys.stdout.flush()
    try:
        user_code = input("Please enter the CAPTCHA text: ").strip()
    except EOFError:
        print("[Error] EOF encountered while reading CAPTCHA input.", flush=True)
        return ""

    print(f"[CAPTCHA RECEIVED] User entered: {user_code}", flush=True)
    return user_code


def main() -> None:
    print("=" * 70, flush=True)
    print("STARTING REAL INPASS RESEARCH SERVICE SMOKE TEST", flush=True)
    print("Theme: WATER", flush=True)
    print("max_queries: 1", flush=True)
    print("max_results_per_query: 2", flush=True)
    print("=" * 70, flush=True)

    service = ResearchService()

    try:
        result = service.run_patent_research(
            theme="WATER",
            max_queries=1,
            max_results_per_query=2,
            captcha_solver=solve_captcha,
        )
    except Exception as exc:
        print(f"\n[FATAL ERROR] ResearchService raised an exception: {exc}", flush=True)
        sys.exit(1)

    print("\n" + "=" * 70, flush=True)
    print("RESEARCH RUN EXECUTION FINISHED", flush=True)
    print("=" * 70, flush=True)

    # Output requested telemetry
    print(f"Research run ID: {result.run_id}")
    print(f"Generated query: {list(result.generated_queries)}")
    print(f"Executed query: {list(result.executed_queries)}")
    print(f"Number of result rows discovered: {result.discovered_count}")
    print(f"Number of patents successfully parsed: {result.ingested_count}")
    print(f"Number inserted: {result.inserted_count}")
    print(f"Number already existing: {result.existing_count}")
    print(f"Number linked to the run: {result.linked_count}")
    print(f"Final run status: {result.final_run_status}")
    if result.error:
        print(f"Error: {result.error}")

    # Inspect persisted patents for this run
    reader = ResearchRunPatentReader()
    patents = reader.get_patents_for_run(result.run_id)

    print("\n--- RETRIEVED PATENTS ---")
    for i, p in enumerate(patents, 1):
        raw = p.raw_data or {}
        app_num = raw.get("application_number", p.patent_number)
        title = p.title or "N/A"
        abstract_len = len(p.abstract) if p.abstract else 0
        spec = raw.get("specification", "") or ""
        claims = raw.get("claims", "") or ""
        spec_len = len(spec)
        claims_len = len(claims)

        print(f"\n[Patent {i}]")
        print(f"  Application Number: {app_num}")
        print(f"  Title: {title}")
        print(f"  Abstract character count: {abstract_len}")
        print(f"  Specification character count: {spec_len}")
        print(f"  Claims character count: {claims_len}")

    passed = (
        result.final_run_status == "completed"
        and result.ingested_count >= 1
        and result.linked_count >= 1
        and len(patents) >= 1
    )
    print(f"\nComplete real workflow passed: {'YES' if passed else 'NO'}", flush=True)

    summary_data = {
        "run_id": result.run_id,
        "theme": result.theme,
        "generated_queries": list(result.generated_queries),
        "executed_queries": list(result.executed_queries),
        "discovered_count": result.discovered_count,
        "ingested_count": result.ingested_count,
        "inserted_count": result.inserted_count,
        "existing_count": result.existing_count,
        "linked_count": result.linked_count,
        "final_run_status": result.final_run_status,
        "error": result.error,
        "patents": [
            {
                "application_number": (p.raw_data or {}).get("application_number", p.patent_number),
                "title": p.title,
                "abstract_length": len(p.abstract) if p.abstract else 0,
                "specification_length": len((p.raw_data or {}).get("specification", "") or ""),
                "claims_length": len((p.raw_data or {}).get("claims", "") or ""),
            }
            for p in patents
        ],
        "passed": passed,
    }
    with open("smoke_test_result.json", "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)


if __name__ == "__main__":
    main()
