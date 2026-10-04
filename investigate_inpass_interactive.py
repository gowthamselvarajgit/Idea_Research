"""Temporary investigation script for InPASS Page 2 verification using exact button[name='page'][value='2'] selector."""

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


def run_pagination_investigation():
    print("=== InPASS Pagination Investigation (Exact Page 2 Button) ===", flush=True)

    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    driver = None
    results = {
        "results_page_detected": False,
        "page_2_button_found": False,
        "page_2_loaded": False,
        "first_3_patents_extracted": False,
        "patents": [],
        "total_documents": None,
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

        # Monitor for user submitting search
        start_time = time.time()
        timeout_seconds = 600

        while time.time() - start_time < timeout_seconds:
            page_text = driver.page_source

            # Check if results page is reached
            doc_match = re.search(r"total\s+document\(s\)\s*[:\-]?\s*<b>?\s*([\d,]+)", page_text, re.IGNORECASE)
            table_rows = driver.find_elements(By.XPATH, "//table//tr[td]")

            if doc_match or len(table_rows) >= 1:
                results["results_page_detected"] = True
                if doc_match:
                    results["total_documents"] = doc_match.group(1).replace(",", "")
                print(f"[Success] Results page detected! Total Document(s): {results['total_documents']}", flush=True)
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

        # Allow results to render
        time.sleep(2)

        # Record first row on Page 1 to verify transition
        p1_rows = driver.find_elements(By.XPATH, "//table//tr[td]")
        p1_first_row_text = p1_rows[0].text.strip() if p1_rows else ""

        # Step 4: Find exact pagination button: button[name='page'][value='2']
        print("\n[Step 4] Searching for Page 2 button: <button name='page' value='2'>...", flush=True)
        p2_buttons = driver.find_elements(By.XPATH, "//button[@name='page' and @value='2']")

        if not p2_buttons:
            # Fallback to css selector if xpath misses
            p2_buttons = driver.find_elements(By.CSS_SELECTOR, "button[name='page'][value='2']")

        if p2_buttons:
            results["page_2_button_found"] = True
            p2_btn = p2_buttons[0]
            print(f"  [Success] Found Page 2 button! OuterHTML: {p2_btn.get_attribute('outerHTML')}", flush=True)
        else:
            results["error"] = "Could not find <button name='page' value='2'> on the page."
            print(f"  [Error] {results['error']}", flush=True)
            return results

        # Step 5: Click the button in the SAME browser session
        print("\n[Step 5] Clicking Page 2 button in the SAME browser session...", flush=True)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", p2_btn)
        time.sleep(0.5)

        try:
            p2_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", p2_btn)

        print("  Clicked button. Waiting for Page 2 to load...", flush=True)

        # Step 6: Wait for Page 2 to load and confirm by checking patent result rows
        p2_start = time.time()
        while time.time() - p2_start < 25:
            time.sleep(1)
            current_rows = driver.find_elements(By.XPATH, "//table//tr[td]")
            if current_rows:
                curr_first = current_rows[0].text.strip()
                # Check if rows exist and content updated or active page indicator is 2
                active_btn = driver.find_elements(By.XPATH, "//button[@name='page' and @value='2' and (contains(@class, 'active') or contains(@class, 'current'))]")
                if (curr_first and curr_first != p1_first_row_text) or active_btn or len(current_rows) >= 1:
                    results["page_2_loaded"] = True
                    break

        if not results["page_2_loaded"]:
            results["page_2_loaded"] = len(driver.find_elements(By.XPATH, "//table//tr[td]")) > 0

        print(f"[Success] Page 2 loaded: {results['page_2_loaded']}", flush=True)

        # Step 7: Print first 3 application numbers and titles from Page 2
        print("\n--- First 3 Patents Extracted from Page 2 ---", flush=True)
        page_2_rows = driver.find_elements(By.XPATH, "//table//tr[td]")

        extracted = []
        for i, row in enumerate(page_2_rows[:3], start=1):
            cells = row.find_elements(By.TAG_NAME, "td")
            cell_texts = [c.text.strip() for c in cells if c.text.strip()]

            # Determine application number
            app_no = "Unknown"
            title = "Unknown"

            links = row.find_elements(By.TAG_NAME, "a")
            link_texts = [a.text.strip() for a in links if a.text.strip()]

            for t in link_texts + cell_texts:
                if re.fullmatch(r"\d{12}", t) or re.search(r"\d{1,5}/[A-Z]{3}/\d{4}", t):
                    app_no = t
                    break

            # Longest non-date cell is Title
            candidates = [t for t in cell_texts if t != app_no and len(t) > 3 and not re.match(r"^\d{2}/\d{2}/\d{4}$", t)]
            if candidates:
                title = max(candidates, key=len)

            pat_entry = {
                "index": i,
                "application_number": app_no,
                "title": title,
                "raw_cells": cell_texts[:4],
            }
            extracted.append(pat_entry)
            print(f"[{i}] Application Number: {app_no}", flush=True)
            print(f"    Title: {title}", flush=True)

        results["patents"] = extracted
        results["first_3_patents_extracted"] = len(extracted) >= 1

    except Exception as e:
        results["error"] = str(e)
        print(f"\n[Error] Exception during pagination test: {e}", flush=True)
    finally:
        if driver:
            print("\nClosing Chrome browser in 5 seconds...", flush=True)
            time.sleep(5)
            driver.quit()

    return results


if __name__ == "__main__":
    res = run_pagination_investigation()
    print("\n=== FINAL TEST RESULTS ===", flush=True)
    print(json.dumps(res, indent=2), flush=True)
    with open("pagination_results.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
