import json
import re
import html

INPUT_JSON_PATH = "/Users/mahadi/Desktop/html_free_treatment/extracted_raw_data.json"
OUTPUT_JSON_PATH = "/Users/mahadi/Desktop/html_free_treatment/cleaned_data.json"

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def clean_text(text):
    """
    Convert HTML / Word-exported content into plain text.
    Removes:
    - HTML tags
    - script/style/head/noscript blocks
    - HTML comments
    - CSS boilerplate like /* Style Definitions */ and mso- styles
    - URLs, file refs, extra whitespace
    """
    if not text or not isinstance(text, str):
        return ""

    text = html.unescape(text)
    text = text.replace("\ufeff", " ").replace("\u200b", " ")

    # First pass: parse HTML properly if BeautifulSoup is available
    if BeautifulSoup is not None:
        soup = BeautifulSoup(text, "html.parser")

        for tag in soup(["script", "style", "noscript", "iframe", "object", "embed", "head", "meta", "link"]):
            tag.decompose()

        text = soup.get_text(" ")

    else:
        # Fallback: remove whole blocks first, then strip tags
        text = re.sub(r"(?is)<!--.*?-->", " ", text)
        text = re.sub(r"(?is)<(script|style|noscript|iframe|object|embed|head|meta|link)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?i)<br\s*/?>", " ", text)
        text = re.sub(r"(?i)</(p|div|li|tr|td|th|h[1-6])>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)

    # Remove leftover HTML comments / CSS blocks if they survived as plain text
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?is)/\*.*?\*/", " ", text)

    # Remove Word/Office CSS-style rule leftovers
    # Example: table.MsoNormalTable { ... }
    text = re.sub(r"(?is)\b[\w.#:-]+\s*\{[^{}]*\}", " ", text)

    # Remove repeated CSS declaration runs like:
    # mso-style-name:"Table Normal"; mso-padding-alt:0cm 5.4pt ...
    if "mso-" in text.lower() or "style definitions" in text.lower() or "{" in text or "}" in text:
        text = re.sub(r"(?is)(?:\b[a-z-]+\s*:\s*[^;{}]+;\s*){2,}", " ", text)

    # Remove URLs and file-like references
    text = re.sub(r"http\S+|www\S+", " ", text)
    text = re.sub(r"\b\S+\.(?:png|jpg|jpeg|gif|pdf|svg|doc|docx|xls|xlsx)\b", " ", text, flags=re.IGNORECASE)

    # Remove any remaining HTML-ish fragments and control whitespace
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()

    return text


def safe_int(value):
    try:
        if value is None:
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def build_maps(data):
    disease_name_map = {}
    disease_to_category_id_map = {}
    category_name_map = {}

    for row in data.get("diseases", []):
        disease_id = safe_int(row.get("id"))
        if disease_id is None:
            continue

        disease_name_map[disease_id] = row.get("name", "") or ""
        disease_to_category_id_map[disease_id] = safe_int(row.get("category_of_disease_id"))

    for row in data.get("category_of_disease", []):
        category_id = safe_int(row.get("id"))
        if category_id is None:
            continue

        category_name_map[category_id] = row.get("name", "") or ""

    return disease_name_map, disease_to_category_id_map, category_name_map


def clean_treatment_rows(raw_treatment_rows, disease_name_map, disease_to_category_id_map, category_name_map):
    final_rows = []

    for row in raw_treatment_rows:
        disease_id = safe_int(row.get("disease_id"))

        disease_name = disease_name_map.get(disease_id, "")
        category_id = disease_to_category_id_map.get(disease_id)
        category_name = category_name_map.get(category_id, "")

        title = clean_text(row.get("title", ""))

        description = row.get("description")
        if not description:
            description = row.get("description_web") or row.get("description_api") or ""

        # Make description fully plain text
        description = clean_text(description)

        final_row = {
            "title": title,
            "disease_name": disease_name,
            "category_of_disease": category_name,
            "description": description
        }

        final_rows.append(final_row)

    return final_rows


def process_cleaning_pipeline(input_json_path, output_json_path):
    print(f"Loading raw extracted records from: {input_json_path}")
    with open(input_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    disease_name_map, disease_to_category_id_map, category_name_map = build_maps(data)

    raw_treatment_rows = data.get("treatment", [])
    cleaned_treatment_rows = clean_treatment_rows(
        raw_treatment_rows,
        disease_name_map,
        disease_to_category_id_map,
        category_name_map
    )

    final_data = {
        "treatment": cleaned_treatment_rows
    }

    with open(output_json_path, "w", encoding="utf-8") as out:
        json.dump(final_data, out, indent=4, ensure_ascii=False)

    print("🧼 Cleaning complete!")
    print(f"Cleaned records saved to: {output_json_path}")


if __name__ == "__main__":
    try:
        process_cleaning_pipeline(INPUT_JSON_PATH, OUTPUT_JSON_PATH)
        print("\n=== SUCCESS: DATA CLEANING COMPLETE ===")
    except FileNotFoundError:
        print(f"❌ ERROR: Could not find '{INPUT_JSON_PATH}'. Please run the extract step first.")
