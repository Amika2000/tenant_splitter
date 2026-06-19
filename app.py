import streamlit as st
import pdfplumber
from pypdf import PdfReader, PdfWriter
from collections import defaultdict
import os
import re
from datetime import datetime
import zipfile
import tempfile

st.set_page_config(page_title="Tenant PDF Splitter", layout="centered")

st.title("JSDS Tenant PDF Splitter")
st.write("Upload bulk PDFs and download separated tenant files.")

# -----------------------------
# Upload
# -----------------------------
statements = st.file_uploader("Upload Statements PDF", type="pdf")
invoices = st.file_uploader("Upload Invoices PDF", type="pdf")
receipts = st.file_uploader("Upload Receipts PDF", type="pdf")
water = st.file_uploader("Upload Water PDF (optional)", type="pdf")

# -----------------------------
# Utilities
# -----------------------------

def normalize(name):
    name = name.upper()
    name = re.sub(r"\s+", " ", name)
    return name.strip()

def first_two_words(name):
    return " ".join(normalize(name).split()[:2])

def clean_text(s):
    if not isinstance(s, str):
        return ""

    # Remove null bytes
    s = s.replace("\x00", "")

    # Remove non-printable characters
    s = re.sub(r"[^\x20-\x7E]", "", s)

    # Replace characters not allowed in filenames
    s = re.sub(r'[<>:"/\\|?*]', "_", s)

    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s)

    return s.strip()

def extract_park(text):
    t = text.upper()

    if "SAPHIRE" in t or "SAPPHIRE" in t:
        return "SAPPHIRE"
    if "GRAPHITE" in t:
        return "GRAPHITE"
    if "EMERALD" in t:
        return "EMERALD"
    if "SCARLET" in t:
        return "SCARLET"

    return "UNKNOWN"

def extract_godowns(text, tenant_name):
    lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 0]

    for i in range(len(lines)):
        if tenant_name.upper() in lines[i].upper():

            # Check only next 3 lines
            for next_line in lines[i + 1:i + 4]:
                up = next_line.upper()

                # Ignore dates
                if re.fullmatch(r"\d{2}/\d{2}/\d{4}", up):
                    continue

                # Ignore PO Boxes
                if "P O BOX" in up or "P.O BOX" in up or "PO BOX" in up:
                    continue

                # Valid godown = any other line with a digit
                if re.search(r"\d", up):
                    m = re.search(r"\d.*", up)
                    return clean_text(m.group())

            return "(OP)"

    return "(OP)"

def extract_month_year(text):
    m = re.search(r"\b\d{2}/\d{2}/\d{4}\b", text)

    if not m:
        return "UNKNOWN_DATE"

    dt = datetime.strptime(m.group(), "%d/%m/%Y")
    return dt.strftime("%b %y").upper()

def extract_tenant_name(text):
    lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 2]

    for i in range(len(lines)):
        low = lines[i].lower()

        if low == "invoice to" or low == "to:":
            if i + 1 < len(lines):
                return lines[i + 1]

        if "received from" in low:
            if i + 1 < len(lines):
                return lines[i + 1]

        if low.endswith(" statement"):
            return lines[i].replace("Statement", "").strip()

    return None

# -----------------------------
# Core Logic
# -----------------------------

def process_bulk_pdf(file, doc_type, tenants):
    file.seek(0)

    with pdfplumber.open(file) as pdf:

        file.seek(0)
        reader = PdfReader(file)

        current_key = None

        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""

            raw = extract_tenant_name(text)

            if raw:
                current_key = clean_text(first_two_words(raw))

                # Only statements define metadata
                if doc_type == "statement":
                    tenants[current_key]["park"] = extract_park(text)
                    tenants[current_key]["godowns"] = extract_godowns(text, raw)
                    tenants[current_key]["date"] = extract_month_year(text)

            if current_key:
                tenants[current_key][doc_type].append(reader.pages[i])

# -----------------------------
# Run
# -----------------------------

if st.button("Process PDFs"):

    if not (statements and invoices and receipts):
        st.error("Please upload Statements, Invoices and Receipts PDFs.")
    else:

        with st.spinner("Processing PDFs..."):

            with tempfile.TemporaryDirectory() as tmp:

                output = os.path.join(tmp, "output")
                os.makedirs(output)

                tenants = defaultdict(lambda: defaultdict(list))

                process_bulk_pdf(statements, "statement", tenants)
                process_bulk_pdf(invoices, "invoice", tenants)
                process_bulk_pdf(receipts, "receipt", tenants)

                if water:
                    process_bulk_pdf(water, "water", tenants)

                # Build tenant PDFs
                for key, docs in tenants.items():

                    writer = PdfWriter()

                    for doc_type in ["statement", "invoice", "water", "receipt"]:
                        for page in docs.get(doc_type, []):
                            writer.add_page(page)

                    clean_key = clean_text(key)
                    park = clean_text(docs.get("park", "UNKNOWN"))
                    godowns = clean_text(docs.get("godowns", "")).replace("/", "_")
                    date = clean_text(docs.get("date", "UNKNOWN_DATE"))

                    park_dir = os.path.join(output, park)
                    os.makedirs(park_dir, exist_ok=True)

                    filename = f"{clean_key} {godowns} - {date}.pdf"
                    path = os.path.join(park_dir, filename)

                    with open(path, "wb") as f:
                        writer.write(f)

                # Create ZIP
                zip_path = os.path.join(tmp, "tenant_pdfs.zip")

                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                    for root, _, files in os.walk(output):
                        for file_name in files:
                            full_path = os.path.join(root, file_name)
                            archive_name = os.path.relpath(full_path, output)
                            z.write(full_path, archive_name)

                with open(zip_path, "rb") as f:
                    st.success(f"Processing complete. Generated {len(tenants)} tenant PDFs.")

                    st.download_button(
                        label="Download ZIP",
                        data=f,
                        file_name="tenant_pdfs.zip",
                        mime="application/zip"
                    )
