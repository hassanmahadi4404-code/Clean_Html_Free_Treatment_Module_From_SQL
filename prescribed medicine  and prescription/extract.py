import re
import json


# ─────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def find_tuple_end(content, start):
    """
    Walk forward from the opening '(' at `start`, respecting single-quoted
    strings (with both \\'  and '' escapes) and nested parentheses, and return
    the index just AFTER the matching closing ')'.
    Returns -1 if the end is never found.
    """
    i = start
    depth = 0
    in_string = False

    while i < len(content):
        c = content[i]

        if in_string:
            if c == '\\':                    # backslash escape
                i += 2
                continue
            elif c == "'":
                if i + 1 < len(content) and content[i + 1] == "'":
                    i += 2                   # '' escape → keep going
                    continue
                else:
                    in_string = False        # closing quote
        else:
            if c == "'":
                in_string = True
            elif c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return i + 1            # found the matching closing paren

        i += 1

    return -1


def parse_sql_tuple(s):
    """
    Parse a complete SQL VALUES tuple string (including the outer parentheses)
    into a Python list of field values.

    Handles:
      • integer / NULL literals
      • single-quoted strings with \\' and '' escapes
      • HTML content with commas, nested parens, backticks, etc.
    """
    s = s.strip()
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1]

    fields = []
    current = ''
    in_string = False
    i = 0

    while i < len(s):
        c = s[i]

        if not in_string:
            if c == "'":
                in_string = True
                i += 1
                continue
            elif c == ',':
                fields.append(current.strip())
                current = ''
                i += 1
                # skip whitespace after comma
                while i < len(s) and s[i] in (' ', '\n', '\r', '\t'):
                    i += 1
                continue
            else:
                current += c

        else:  # inside a single-quoted string
            if c == '\\':
                if i + 1 < len(s):
                    nc = s[i + 1]
                    if nc == "'":
                        current += "'";  i += 2; continue
                    elif nc == '\\':
                        current += '\\'; i += 2; continue
                    elif nc == 'n':
                        current += '\n'; i += 2; continue
                    elif nc == 'r':
                        current += '\r'; i += 2; continue
                    elif nc == 't':
                        current += '\t'; i += 2; continue
                current += c   # lone backslash – pass through
            elif c == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    current += "'"   # '' escape
                    i += 2
                    continue
                else:
                    in_string = False   # end of string literal
                    i += 1
                    continue
            else:
                current += c

        i += 1

    fields.append(current.strip())
    return fields


# ─────────────────────────────────────────────────────────────────────────────
# Per-table extractors
# ─────────────────────────────────────────────────────────────────────────────

def extract_simple_tables(content, target_tables):
    """
    Extracts rows from tables whose VALUES are simple (no huge HTML blobs).
    Uses the original tokeniser – fast enough for prescription / prescribed_medicine.
    """
    extracted = {t: [] for t in target_tables}

    insert_re = re.compile(
        r'INSERT INTO `([^`]+)`\s*(?:\([^)]+\))?\s*VALUES\s*(.*?);',
        re.DOTALL | re.IGNORECASE
    )

    for match in insert_re.finditer(content):
        table_name = match.group(1)
        if table_name not in extracted:
            continue

        values_content = match.group(2).strip()
        raw_rows = re.findall(r'\((.*?)\)(?:\s*,\s*|\s*$)', values_content, re.DOTALL)

        for raw_row in raw_rows:
            tokens = re.findall(r"'(.*?)'(?=\s*,|\s*$)|(\d+)|(NULL)", raw_row, re.DOTALL)
            cleaned_row = []
            for t in tokens:
                if t[0]:                 # string match
                    cleaned_row.append(t[0])
                elif t[1]:               # numeric match
                    cleaned_row.append(int(t[1]))
                else:                    # NULL
                    cleaned_row.append(None)

            if cleaned_row:
                extracted[table_name].append(cleaned_row)

    return extracted


def extract_treatment_table(content):
    """
    Extracts ALL columns from the `treatment` table using a proper state-machine
    parser that correctly handles large HTML content with nested quotes and commas.

    Returns a list of dicts with keys:
      id, title, description, description_web, description_api, disease_id, indexing
    """
    rows = []
    errors = 0

    insert_positions = [m.start() for m in re.finditer(r'INSERT INTO `treatment`', content)]
    print(f"  Found {len(insert_positions)} INSERT statements for `treatment`")

    for pos in insert_positions:
        # Locate the VALUES keyword
        vals_match = re.search(r'VALUES\s*\n', content[pos: pos + 500])
        if not vals_match:
            print("  WARNING: Could not find VALUES keyword, skipping.")
            continue

        vals_start = pos + vals_match.end()

        # Skip optional whitespace before the opening '('
        while vals_start < len(content) and content[vals_start] in ' \n\r\t':
            vals_start += 1

        if content[vals_start] != '(':
            print(f"  WARNING: Expected '(' at {vals_start}, "
                  f"got {content[vals_start:vals_start+10]!r}")
            continue

        row_end = find_tuple_end(content, vals_start)
        if row_end == -1:
            print(f"  WARNING: Could not find end of tuple at {vals_start}")
            errors += 1
            continue

        row_text = content[vals_start:row_end]

        try:
            fields = parse_sql_tuple(row_text)
        except Exception as exc:
            print(f"  WARNING: parse error – {exc}")
            errors += 1
            continue

        if len(fields) != 7:
            print(f"  WARNING: expected 7 fields, got {len(fields)} "
                  f"for row starting: {row_text[:60]!r}")
            errors += 1
            continue

        rows.append({
            "id":              fields[0],
            "title":           fields[1],
            "description":     fields[2],
            "description_web": fields[3],
            "description_api": fields[4],
            "disease_id":      fields[5],
            "indexing":        fields[6],
        })

    if errors:
        print(f"  {errors} row(s) could not be parsed for `treatment`.")

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def parse_mysql_inserts(sql_file_path):
    print(f"Reading and extracting row entries from: {sql_file_path}...\n")

    with open(sql_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # --- simple tables (prescription, prescribed_medicine) ---
    simple_tables = ["user","prescription", "prescribed_medicine"]
    extracted_data = extract_simple_tables(content, simple_tables)

    # --- treatment table (needs robust parser) ---
    print("Parsing `treatment` table with full SQL state-machine parser...")
    treatment_rows = extract_treatment_table(content)
    extracted_data["treatment"] = treatment_rows

    return extracted_data


if __name__ == "__main__":
    sql_filename = "/Users/mahadi/Desktop/fold/lensnmza_td.sql"

    try:
        raw_dataset = parse_mysql_inserts(sql_filename)

        print("\n=== EXTRACTION SUMMARY ===")
        for table_name, records in raw_dataset.items():
            print(f"📋 Table '{table_name}': Found {len(records)} raw entries.")

        output_json_path = "/Users/mahadi/Desktop/fold/extracted_raw_data.json"
        with open(output_json_path, "w", encoding="utf-8") as out:
            json.dump(raw_dataset, out, indent=4, ensure_ascii=False)

        print("\n=== SUCCESS: DATA EXTRACTION COMPLETE ===")
        print(f"Raw records saved to '{output_json_path}'")

    except FileNotFoundError:
        print(f"❌ ERROR: Could not find '{sql_filename}'. Please check your file paths.")
