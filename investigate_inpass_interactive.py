"""Temporary investigation script for retrieving full InPASS PatentDetails from Page 2."""

import json
import os
import re
import shutil
import sys
import tempfile
import time

# Ensure immediate line-buffered stdout
sys.stdout.reconfigure(line_buffering=True)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

INPASS_URL = "https://iprsearch.ipindia.gov.in/publicsearch"
TARGET_APP_NUM = "202641109752"


def run_details_investigation():
    print("=== InPASS PatentDetails Investigation ===", flush=True)

    temp_profile_dir = tempfile.mkdtemp(prefix="chrome_inpass_profile_")

    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(f"--user-data-dir={temp_profile_dir}")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = None
    results = {
        "results_page_detected": False,
        "page_2_loaded": False,
        "target_app_num": TARGET_APP_NUM,
        "patent_details_page_loaded": False,
        "extracted_fields": {},
        "complete_specification_exists": False,
        "complete_specification_length": 0,
        "claims_exist": False,
        "claims_length": 0,
        "error": None,
    }

    try:
        print("[Step 1] Opening visible Chrome browser...", flush=True)
        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 30)

        print(f"[Step 2] Navigating to {INPASS_URL}...", flush=True)
        driver.get(INPASS_URL)

        # Wait for form
        wait.until(EC.presence_of_element_located((By.NAME, "ItemField1")))
        time.sleep(1)

        print("[Step 3] Pre-filling search fields...", flush=True)
        # 1. Published checkbox: checked
        pub_cb = driver.find_element(By.ID, "Published")
        if not pub_cb.is_selected():
            pub_cb.click()

        # 2. Granted checkbox: unchecked
        grant_cb = driver.find_element(By.ID, "Granted")
        if grant_cb.is_selected():
            grant_cb.click()

        # 3. Date field: Application Date (National) - APD
        try:
            date_select = Select(driver.find_element(By.ID, "DateField"))
            date_select.select_by_value("APD")
        except Exception:
            pass

        # 4. ItemField1: Title (TI)
        item_select = Select(driver.find_element(By.NAME, "ItemField1"))
        item_select.select_by_value("TI")

        # 5. TextField1: WATER
        text_input = driver.find_element(By.NAME, "TextField1")
        text_input.clear()
        text_input.send_keys("WATER")

        # 6. LogicField1: AND
        try:
            logic_select = Select(driver.find_element(By.NAME, "LogicField1"))
            logic_select.select_by_value("AND")
        except Exception:
            pass

        print("\n" + "=" * 65, flush=True)
        print(">>> CHECKPOINT: Please enter the CAPTCHA manually and submit/continue. <<<", flush=True)
        print("=" * 65, flush=True)
        print("Waiting for CAPTCHA submission and search results page (timeout: 10 minutes)...\n", flush=True)

        start_time = time.time()
        timeout_seconds = 600
        initial_url = driver.current_url

        search_submitted = False
        results_detected = False

        # Stage 1: Detect CAPTCHA submission and Search Results
        while time.time() - start_time < timeout_seconds:
            try:
                current_url = driver.current_url
                page_source = driver.page_source

                # Detect if search was submitted and results arrived
                has_page_btns = len(driver.find_elements(By.XPATH, "//button[@name='page']")) > 0
                has_app_btns = len(driver.find_elements(By.XPATH, "//*[@name='ApplicationNumber']")) > 0
                has_result_rows = len(driver.find_elements(By.XPATH, "//table//tr[td[contains(., 'Published') or contains(., '202')]]")) > 0
                url_changed = (current_url != initial_url) and ("/search" in current_url.lower() or "publicationsearch" in current_url.lower())

                if has_page_btns or has_app_btns or has_result_rows or ("total document" in page_source.lower() and url_changed):
                    if not search_submitted:
                        print("CAPTCHA submitted", flush=True)
                        search_submitted = True
                    print("Search results detected", flush=True)
                    results_detected = True
                    results["results_page_detected"] = True
                    break

                if "invalid captcha" in page_source.lower():
                    print("  [Notice] Server indicated 'Invalid captcha'. Please re-enter and submit.", flush=True)
                    time.sleep(2)
                    continue

            except Exception:
                pass

            time.sleep(0.5)

        if not results_detected:
            results["error"] = "Timed out waiting for CAPTCHA submission and search results."
            print(f"[Error] {results['error']}", flush=True)
            return results

        time.sleep(1.5)

        # Stage 2: Click Page 2 and detect Page 2
        p2_buttons = driver.find_elements(By.XPATH, "//button[@name='page' and @value='2']")
        if not p2_buttons:
            p2_buttons = driver.find_elements(By.CSS_SELECTOR, "button[name='page'][value='2']")

        if not p2_buttons:
            results["error"] = "Could not find button[name='page'][value='2'] on results page."
            print(f"[Error] {results['error']}", flush=True)
            return results

        p2_btn = p2_buttons[0]
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", p2_btn)
        time.sleep(0.5)

        try:
            p2_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", p2_btn)

        # Wait until Page 2 is fully loaded
        p2_start = time.time()
        p2_loaded = False
        while time.time() - p2_start < 30:
            try:
                page_source = driver.page_source
                if TARGET_APP_NUM in page_source or len(driver.find_elements(By.XPATH, f"//*[contains(., '{TARGET_APP_NUM}')]")) > 0:
                    p2_loaded = True
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if not p2_loaded:
            # Fallback confirmation
            p2_loaded = len(driver.find_elements(By.XPATH, "//table//tr[td]")) > 0

        print("Page 2 detected", flush=True)
        results["page_2_loaded"] = True
        time.sleep(1)

        # Stage 3: Find Application 202641109752 on Page 2 and click its button
        app_elements = driver.find_elements(
            By.XPATH,
            f"//button[@name='ApplicationNumber' and (@value='{TARGET_APP_NUM}' or contains(text(), '{TARGET_APP_NUM}'))] "
            f"| //input[@name='ApplicationNumber' and @value='{TARGET_APP_NUM}'] "
            f"| //tr[contains(., '{TARGET_APP_NUM}')]//*[@name='ApplicationNumber'] "
            f"| //tr[contains(., '{TARGET_APP_NUM}')]//button "
            f"| //tr[contains(., '{TARGET_APP_NUM}')]//a"
        )

        if not app_elements and TARGET_APP_NUM not in driver.page_source:
            results["error"] = f"Application {TARGET_APP_NUM} not found on Page 2."
            print(f"[Error] {results['error']}", flush=True)
            return results

        print(f"Application {TARGET_APP_NUM} found", flush=True)

        initial_handles = driver.window_handles
        initial_window = driver.current_window_handle

        if app_elements:
            target_el = app_elements[0]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_el)
            time.sleep(0.5)
            try:
                target_el.click()
            except Exception:
                driver.execute_script("arguments[0].click();", target_el)
        else:
            submit_script = f"""
                var form = document.createElement('form');
                form.method = 'POST';
                form.action = '/PublicSearch/PublicationSearch/PatentDetails';
                form.target = '_self';
                var f1 = document.createElement('input'); f1.name = 'ApplicationNumber'; f1.value = '{TARGET_APP_NUM}'; form.appendChild(f1);
                var f2 = document.createElement('input'); f2.name = 'ConnectionName'; f2.value = 'PublicationConnection'; form.appendChild(f2);
                var f3 = document.createElement('input'); f3.name = 'IP'; f3.value = '163.53.207.117'; form.appendChild(f3);
                document.body.appendChild(form);
                form.submit();
            """
            driver.execute_script(submit_script)

        # Stage 4: Wait for PatentDetails
        pd_start = time.time()
        pd_loaded = False
        while time.time() - pd_start < 30:
            try:
                new_handles = driver.window_handles
                if len(new_handles) > len(initial_handles):
                    for h in new_handles:
                        if h != initial_window:
                            driver.switch_to.window(h)
                            break
                src_lower = driver.page_source.lower()
                if "complete specification" in src_lower or "patent details" in src_lower or TARGET_APP_NUM in src_lower:
                    pd_loaded = True
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if not pd_loaded:
            results["error"] = "PatentDetails page did not appear to load."
            print(f"[Error] {results['error']}", flush=True)
            return results

        print("PatentDetails loaded", flush=True)
        details_html = driver.page_source
        results["patent_details_page_loaded"] = True

        # Stage 5: Parser verification
        print("Parser verification started", flush=True)

        from src.patents.inpass_parser import parse_inpass_patent_details
        parsed_record = parse_inpass_patent_details(details_html)

        spec_len = len(parsed_record.specification) if parsed_record.specification else 0
        claims_len = len(parsed_record.claims) if parsed_record.claims else 0
        app_count = len(parsed_record.applicants)
        inv_count = len(parsed_record.inventors)

        discrepancies = []
        if parsed_record.application_number != TARGET_APP_NUM:
            discrepancies.append(f"Application Number: expected {TARGET_APP_NUM}, got {parsed_record.application_number}")
        if parsed_record.publication_number != "38/2026":
            discrepancies.append(f"Publication Number: expected 38/2026, got {parsed_record.publication_number}")
        if parsed_record.publication_date != "18/09/2026":
            discrepancies.append(f"Publication Date: expected 18/09/2026, got {parsed_record.publication_date}")
        if parsed_record.filing_date != "12/09/2026":
            discrepancies.append(f"Filing Date: expected 12/09/2026, got {parsed_record.filing_date}")
        if not parsed_record.title or "MICROPLASTICS" not in parsed_record.title.upper():
            discrepancies.append(f"Title: unexpected value '{parsed_record.title}'")
        if not parsed_record.ipc or "G01N" not in parsed_record.ipc:
            discrepancies.append(f"IPC: unexpected value '{parsed_record.ipc}'")
        if app_count != 7:
            discrepancies.append(f"Applicant count: expected 7, got {app_count}")
        if inv_count != 7:
            discrepancies.append(f"Inventor count: expected 7, got {inv_count}")
        if not parsed_record.abstract:
            discrepancies.append("Abstract is empty")
        if spec_len < 30000:
            discrepancies.append(f"Specification length: {spec_len} (expected ~40,365)")
        if claims_len < 1500:
            discrepancies.append(f"Claims length: {claims_len} (expected ~1,989)")

        app_names = [a.name for a in parsed_record.applicants]
        if len(set(app_names)) < 5:
            discrepancies.append("Applicant names do not appear correctly separated")

        inv_names = [inv.name for inv in parsed_record.inventors]
        if len(set(inv_names)) < 5:
            discrepancies.append("Inventor names do not appear correctly separated")

        test_passed = len(discrepancies) == 0

        if test_passed:
            print("Parser verification PASS", flush=True)
            print("\nREAL INPASS PARSER TEST: PASS", flush=True)
        else:
            print("Parser verification FAIL", flush=True)
            print("\nREAL INPASS PARSER TEST: FAIL", flush=True)

        print("\n--- Parsed Field Summary ---", flush=True)
        print(f"Application Number         : {parsed_record.application_number}", flush=True)
        print(f"Publication Number         : {parsed_record.publication_number}", flush=True)
        print(f"Publication Date           : {parsed_record.publication_date}", flush=True)
        print(f"Filing Date                : {parsed_record.filing_date}", flush=True)
        print(f"Invention Title            : {parsed_record.title}", flush=True)
        print(f"IPC                        : {parsed_record.ipc}", flush=True)
        print(f"Applicant Count            : {app_count}", flush=True)
        for i, a in enumerate(parsed_record.applicants, 1):
            print(f"  {i}. {a.name} | {a.address[:35]}... | {a.country} | {a.nationality}", flush=True)
        print(f"Inventor Count             : {inv_count}", flush=True)
        for i, inv in enumerate(parsed_record.inventors, 1):
            print(f"  {i}. {inv.name} | {inv.address[:35]}... | {inv.country} | {inv.nationality}", flush=True)
        print(f"Abstract Non-Empty         : {bool(parsed_record.abstract)}", flush=True)
        print(f"Specification Char Count   : {spec_len}", flush=True)
        print(f"Claims Char Count          : {claims_len}", flush=True)
        if discrepancies:
            print("\nDiscrepancies Found:", flush=True)
            for d in discrepancies:
                print(f"  - {d}", flush=True)
        else:
            print("\nNo discrepancies found. All expected values verified!", flush=True)

        results["parsed_record"] = parsed_record.to_dict()
        results["test_passed"] = test_passed
        results["discrepancies"] = discrepancies
        results["spec_length"] = spec_len
        results["claims_length"] = claims_len
        results["applicant_count"] = app_count
        results["inventor_count"] = inv_count

    except Exception as e:
        results["error"] = str(e)
        print(f"\n[Error] Exception during details investigation: {e}", flush=True)
    finally:
        if driver:
            print("\nClosing Chrome browser in 5 seconds...", flush=True)
            time.sleep(5)
            try:
                driver.quit()
            except Exception:
                pass
        try:
            shutil.rmtree(temp_profile_dir, ignore_errors=True)
        except Exception:
            pass

    return results


if __name__ == "__main__":
    res = run_details_investigation()
    with open("patent_details_result.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
