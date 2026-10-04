"""Temporary investigation script for retrieving full InPASS PatentDetails from Page 2."""

import json
import re
import sys
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

    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

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
        print("Waiting for search results page to load (timeout: 10 minutes)...\n", flush=True)

        start_time = time.time()
        timeout_seconds = 600

        while time.time() - start_time < timeout_seconds:
            page_text = driver.page_source
            table_rows = driver.find_elements(By.XPATH, "//table//tr[td]")

            if "total document" in page_text.lower() or len(table_rows) >= 1:
                results["results_page_detected"] = True
                print("[Success] Search results page detected!", flush=True)
                break

            if "invalid captcha" in page_text.lower():
                print("  [Notice] Server indicated 'Invalid captcha'. Please re-enter and submit.", flush=True)
                time.sleep(2)
                continue

            time.sleep(1)

        if not results["results_page_detected"]:
            results["error"] = "Timed out waiting for CAPTCHA submission and search results."
            print(f"[Error] {results['error']}", flush=True)
            return results

        time.sleep(2)

        # Step 4: Click Page 2
        print("\n[Step 4] Navigating to Page 2 using button[name='page'][value='2']...", flush=True)
        p2_buttons = driver.find_elements(By.XPATH, "//button[@name='page' and @value='2']")
        if not p2_buttons:
            p2_buttons = driver.find_elements(By.CSS_SELECTOR, "button[name='page'][value='2']")

        if not p2_buttons:
            results["error"] = "Could not find button[name='page'][value='2'] on the results page."
            print(f"[Error] {results['error']}", flush=True)
            return results

        p2_btn = p2_buttons[0]
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", p2_btn)
        time.sleep(0.5)

        try:
            p2_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", p2_btn)

        # Wait for Page 2 to load
        print("  Waiting for Page 2 rows to load...", flush=True)
        p2_loaded = False
        p2_start = time.time()
        while time.time() - p2_start < 25:
            time.sleep(1)
            p2_rows = driver.find_elements(By.XPATH, "//table//tr[td]")
            if p2_rows:
                row_texts = [r.text for r in p2_rows]
                if any(TARGET_APP_NUM in t for t in row_texts):
                    p2_loaded = True
                    break

        if not p2_loaded:
            print(f"  [Notice] Checking page rows directly for target application number {TARGET_APP_NUM}...", flush=True)

        results["page_2_loaded"] = True
        print(f"[Success] Page 2 confirmed loaded!", flush=True)

        # Step 5: Open PatentDetails for target application number 202641109752
        print(f"\n[Step 5] Locating and opening PatentDetails for {TARGET_APP_NUM}...", flush=True)

        initial_handles = driver.window_handles
        initial_window = driver.current_window_handle

        # Locate the link or button associated with TARGET_APP_NUM
        target_links = driver.find_elements(By.XPATH, f"//table//tr[td[contains(., '{TARGET_APP_NUM}')]]//a | //table//tr[td[contains(., '{TARGET_APP_NUM}')]]//button")

        if target_links:
            target_element = target_links[0]
            print(f"  Found interactive element for {TARGET_APP_NUM}: {target_element.get_attribute('outerHTML')[:120]}", flush=True)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_element)
            time.sleep(0.5)
            try:
                target_element.click()
            except Exception:
                driver.execute_script("arguments[0].click();", target_element)
        else:
            print(f"  Direct link not found in row. Submitting PatentDetails form via JavaScript in SAME session...", flush=True)
            # Use legitimate InPASS form POST in current session
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

        # Wait for PatentDetails page to load
        print("  Waiting for PatentDetails page to load...", flush=True)
        time.sleep(4)

        # Check if opened in new tab/window
        new_handles = driver.window_handles
        if len(new_handles) > len(initial_handles):
            for h in new_handles:
                if h != initial_window:
                    driver.switch_to.window(h)
                    break

        details_text = driver.page_source
        is_details = (
            "patent details" in details_text.lower()
            or "complete specification" in details_text.lower()
            or "application number" in details_text.lower()
            or TARGET_APP_NUM in details_text
        )

        results["patent_details_page_loaded"] = is_details
        if not is_details:
            results["error"] = "PatentDetails page did not appear to load."
            print(f"[Error] {results['error']}", flush=True)
            return results

        print("[Success] PatentDetails page loaded successfully!", flush=True)

        # Step 6: Extract required fields
        # Helper to extract text by field label
        def extract_value_for_label(labels):
            for label in labels:
                # Check table cells
                xpath = f"//tr[td[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{label.lower()}')]]/td[2]"
                elems = driver.find_elements(By.XPATH, xpath)
                if elems and elems[0].text.strip():
                    return elems[0].text.strip()
                # Check th/td
                xpath_th = f"//tr[th[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{label.lower()}')]]/td[1]"
                elems_th = driver.find_elements(By.XPATH, xpath_th)
                if elems_th and elems_th[0].text.strip():
                    return elems_th[0].text.strip()
                # Check regex in text
                pattern = rf"{label}\s*[:\-]?\s*([^\n\r<]+)"
                m = re.search(pattern, details_text, re.IGNORECASE)
                if m and m.group(1).strip():
                    return m.group(1).strip()
            return ""

        fields = {}
        fields["Application Number"] = extract_value_for_label(["Application Number", "Application No"]) or TARGET_APP_NUM
        fields["Publication Number"] = extract_value_for_label(["Publication Number", "Publication No"])
        fields["Publication Date"] = extract_value_for_label(["Publication Date", "Date of Publication"])
        fields["Filing Date"] = extract_value_for_label(["Filing Date", "Date of Filing", "Application Date"])
        # Applicant extraction (nested table under Applicant header)
        app_elems = driver.find_elements(By.XPATH, "//tr[td[normalize-space()='Applicant']]/following-sibling::tr[1]//table//tr[td]/td[1]")
        app_names = [e.text.strip() for e in app_elems if e.text.strip()]
        fields["Applicant"] = ", ".join(app_names) if app_names else extract_value_for_label(["Name of Applicant", "Applicant Name", "Applicant"])

        # Inventor extraction (nested table under Inventor header)
        inv_elems = driver.find_elements(By.XPATH, "//tr[td[normalize-space()='Inventor']]/following-sibling::tr[1]//table//tr[td]/td[1]")
        inv_names = [e.text.strip() for e in inv_elems if e.text.strip()]
        fields["Inventor(s)"] = ", ".join(inv_names) if inv_names else extract_value_for_label(["Name of Inventor", "Inventor Name", "Inventor(s)", "Inventors"])

        fields["IPC"] = extract_value_for_label(["International Classification", "IPC Classification", "IPC"])

        # Extract Abstract
        abstract_text = ""
        abs_elems = driver.find_elements(By.XPATH, "//div[contains(@id, 'abstract') or contains(@class, 'abstract')] | //p[preceding-sibling::*[contains(., 'Abstract')]]")
        if abs_elems:
            abstract_text = abs_elems[0].text.strip()
        if not abstract_text:
            m_abs = re.search(r"Abstract\s*[:\-]?\s*<[^>]*>([\s\S]*?)<(?:\/p|\/div|h[1-6])", details_text, re.IGNORECASE)
            if m_abs:
                abstract_text = re.sub(r"<[^>]+>", " ", m_abs.group(1)).strip()
        if not abstract_text:
            abstract_text = extract_value_for_label(["Abstract"])

        fields["Abstract"] = abstract_text

        # Extract Complete Specification & Claims
        spec_text = ""
        spec_elems = driver.find_elements(By.XPATH, "//*[@id='specification' or @id='CompleteSpecification' or @id='spec' or contains(@class, 'specification')]")
        if spec_elems:
            spec_text = spec_elems[0].text.strip()
        if not spec_text:
            m_spec = re.search(r"Complete\s+Specification\s*[:\-]?([\s\S]*?)(?:Claims|\Z)", details_text, re.IGNORECASE)
            if m_spec:
                spec_text = re.sub(r"<[^>]+>", " ", m_spec.group(1)).strip()

        claims_text = ""
        claims_elems = driver.find_elements(By.XPATH, "//*[@id='claims' or @id='Claims' or contains(@class, 'claims')]")
        if claims_elems:
            claims_text = claims_elems[0].text.strip()
        if not claims_text:
            m_claims = re.search(r"Claims\s*[:\-]?([\s\S]*?)(?:<div class=\"footer\"|\Z)", details_text, re.IGNORECASE)
            if m_claims:
                claims_text = re.sub(r"<[^>]+>", " ", m_claims.group(1)).strip()

        has_spec = len(spec_text) > 50 or "complete specification" in details_text.lower()
        has_claims = len(claims_text) > 20 or "claims" in details_text.lower()

        results["extracted_fields"] = fields
        results["complete_specification_exists"] = has_spec
        results["complete_specification_length"] = len(spec_text)
        results["claims_exist"] = has_claims
        results["claims_length"] = len(claims_text)

        # Print all extracted fields cleanly
        print("\n" + "=" * 65, flush=True)
        print("--- EXTRACTED PATENT DETAILS ---", flush=True)
        print("=" * 65, flush=True)
        for k, v in fields.items():
            print(f"{k:<20}: {v}", flush=True)

        print("-" * 65, flush=True)
        print(f"Complete Specification Exists : {has_spec}", flush=True)
        print(f"Complete Specification Length : {len(spec_text)} characters", flush=True)
        print(f"Claims Exist                  : {has_claims}", flush=True)
        print(f"Claims Length                 : {len(claims_text)} characters", flush=True)
        print("=" * 65, flush=True)

    except Exception as e:
        results["error"] = str(e)
        print(f"\n[Error] Exception during details investigation: {e}", flush=True)
    finally:
        if driver:
            print("\nKeeping browser open for 10 seconds before exit...", flush=True)
            time.sleep(10)
            driver.quit()

    return results


if __name__ == "__main__":
    res = run_details_investigation()
    print("\n=== FINAL TEST RESULTS ===", flush=True)
    print(json.dumps(res, indent=2), flush=True)
    with open("patent_details_result.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
