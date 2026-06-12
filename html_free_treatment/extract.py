import re
import json
import html

TABLE_NAME = "treatment"
EXPECTED_COLUMNS = [
    "id",
    "title",
    "description",
    "description_web",
    "description_api",
    "disease_id",
    "indexing",
]

def clean_text(text):
    if not isinstance(text, str):
        return ""

    text = html.unescape(text)
    text = re.sub(r"(?is)<(script|style|xml)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>|</div>|</tr>|</li>|</h[1-6]>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def parse_sql_value(token):
    token = token.strip()

    if token.upper() == "NULL":
        return None

    if token.startswith("'") and token.endswith("'") and len(token) >= 2:
        token = token[1:-1]

    token = (
        token.replace("\\\\", "\\")
             .replace("\\'", "'")
             .replace('\\"', '"')
             .replace("\\n", "\n")
             .replace("\\r", "\r")
             .replace("\\t", "\t")
    )

    token = html.unescape(token)

    if re.fullmatch(r"-?\d+", token):
        try:
            return int(token)
        except ValueError:
            pass

    return token

def find_statement_end(content, start):
    """
    Find the semicolon that ends the INSERT statement.
    Ignores semicolons inside quoted strings.
    """
    in_string = False
    escape = False
    i = start

    while i < len(content):
        ch = content[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                if i + 1 < len(content) and content[i + 1] == "'":
                    i += 1
                else:
                    in_string = False
        else:
            if ch == "'":
                in_string = True
            elif ch == ";":
                return i + 1

        i += 1

    return -1

def extract_tuples(values_text):
    """
    Extract all top-level tuples from a VALUES block.
    """
    tuples = []
    in_string = False
    escape = False
    depth = 0
    start = None
    i = 0

    while i < len(values_text):
        ch = values_text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                if i + 1 < len(values_text) and values_text[i + 1] == "'":
                    i += 1
                else:
                    in_string = False
        else:
            if ch == "'":
                in_string = True
            elif ch == "(":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == ")":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start is not None:
                        tuples.append(values_text[start:i + 1])
                        start = None

        i += 1

    return tuples

def split_tuple_fields(tuple_text):
    """
    Split one SQL tuple into fields by commas outside quoted strings.
    """
    s = tuple_text.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]

    fields = []
    current = []
    in_string = False
    escape = False
    i = 0

    while i < len(s):
        ch = s[i]

        if in_string:
            if escape:
                if ch == "n":
                    current.append("\n")
                elif ch == "r":
                    current.append("\r")
                elif ch == "t":
                    current.append("\t")
                else:
                    current.append(ch)
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    current.append("'")
                    i += 1
                else:
                    in_string = False
            else:
                current.append(ch)
        else:
            if ch == "'":
                in_string = True
            elif ch == ",":
                fields.append("".join(current).strip())
                current = []
            else:
                current.append(ch)

        i += 1

    fields.append("".join(current).strip())
    return fields

def extract_treatment_blocks(content):
    """
    Return a hierarchy:
    [
        {
            "block_no": 1,
            "rows": [ {...}, {...} ]
        },
        ...
    ]
    """
    blocks = []

    insert_re = re.compile(
        r"INSERT INTO\s+`treatment`\s*\((.*?)\)\s*VALUES\s*",
        re.IGNORECASE | re.DOTALL
    )

    matches = list(insert_re.finditer(content))
    print(f"Found {len(matches)} INSERT block(s) for treatment.")

    for block_no, m in enumerate(matches, start=1):
        columns_raw = m.group(1)
        columns = [c.strip(" `") for c in columns_raw.split(",")]

        values_start = m.end()
        values_end = find_statement_end(content, values_start)

        if values_end == -1:
            print(f"Warning: could not find end of INSERT block #{block_no}")
            continue

        values_text = content[values_start:values_end - 1]
        tuple_texts = extract_tuples(values_text)

        block_rows = []

        for tuple_text in tuple_texts:
            fields_raw = split_tuple_fields(tuple_text)
            fields = [parse_sql_value(x) for x in fields_raw]

            if len(fields) != len(columns):
                continue

            record = dict(zip(columns, fields))

            for key in ("title", "description", "description_web", "description_api"):
                if key in record and isinstance(record[key], str):
                    record[key] = clean_text(record[key])

            block_rows.append(record)

        blocks.append({
            "block_no": block_no,
            "rows": block_rows
        })

        print(f"  Block #{block_no}: {len(block_rows)} row(s)")

    return blocks

def parse_mysql_treatment(sql_file_path):
    print(f"Reading: {sql_file_path}")

    with open(sql_file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    treatment_blocks = extract_treatment_blocks(content)

    return {
        "treatment": treatment_blocks
    }

if __name__ == "__main__":
    sql_filename = "/Users/mahadi/Desktop/html_free_treatment/source_sql.sql"
    output_json_path = "/Users/mahadi/Desktop/html_free_treatment/extracted_raw_data copy.json"

    try:
        data = parse_mysql_treatment(sql_filename)

        total_rows = sum(len(block["rows"]) for block in data["treatment"])
        print("\n=== EXTRACTION SUMMARY ===")
        print(f"Total INSERT blocks: {len(data['treatment'])}")
        print(f"Total rows extracted: {total_rows}")

        with open(output_json_path, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=4, ensure_ascii=False)

        print(f"Saved to: {output_json_path}")

    except FileNotFoundError:
        print(f"ERROR: Could not find '{sql_filename}'.")
