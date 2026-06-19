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
# Uploads
# -----------------------------

statements = st.file_uploader(
    "Upload Statements PDF (required)",
    type="pdf"
)

invoices = st.file_uploader(
    "Upload Invoice PDF(s)",
    type="pdf",
    accept_multiple_files=True
)

water = st.file_uploader(
    "Upload Water PDF(s) (optional)",
    type="pdf",
    accept_multiple_files=True
)

receipts = st.file_uploader(
    "Upload Receipt PDF(s)",
    type="pdf",
    accept_multiple_files=True
)

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

    s = s.replace("\x00", "")

    s = re.sub(r"[^\x20-\x7E]", "", s)

    s = re.sub(r'[<>:"/\\|?*]', "_", s)

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

            for next_line in lines[i+1:i+4]:

                up = next_line.upper()

                # Ignore dates
                if re.fullmatch(r"\d{2}/\d{2}/\d{4}", up):
                    continue

                # Ignore PO boxes
                if "P O BOX" in up or "P.O BOX" in up or "PO BOX" in up:
                    continue

                # First remaining line with a number
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

        if low == "invoice to":

            if i+1 < len(lines):
                return lines[i+1]

        if low == "to:":

            if i+1 < len(lines):
                return lines[i+1]

        if "received from" in low:

            if i+1 < len(lines):
                return lines[i+1]

        if low.endswith(" statement"):

            return lines[i].replace("Statement", "").strip()

    return None


# -----------------------------
# Core processing
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

                if doc_type == "statement":

                    tenants[current_key]["park"] = extract_park(text)

                    tenants[current_key]["godowns"] = extract_godowns(
                        text,
                        raw
                    )

                    tenants[current_key]["date"] = extract_month_year(text)

            if current_key:

                tenants[current_key][doc_type].append(
                    reader.pages[i]
                )

# -----------------------------
# Run button
# -----------------------------

if st.button("Process PDFs"):

    if not statements:

        st.error("Please upload Statements PDF.")

    elif len(invoices) == 0:

        st.error("Please upload at least one Invoice PDF.")

    elif len(receipts) == 0:

        st.error("Please upload at least one Receipt PDF.")

    else:

        with st.spinner("Processing PDFs..."):

            with tempfile.TemporaryDirectory() as tmp:

                output = os.path.join(tmp, "output")

                os.makedirs(output)

                tenants = defaultdict(
                    lambda: defaultdict(list)
                )

                # Statements (single bulk PDF)
                process_bulk_pdf(
                    statements,
                    "statement",
                    tenants
                )

                # Multiple invoice PDFs
                for invoice_file in invoices:

                    process_bulk_pdf(
                        invoice_file,
                        "invoice",
                        tenants
                    )

                # Multiple water PDFs
                for water_file in water:

                    process_bulk_pdf(
                        water_file,
                        "water",
                        tenants
                    )

                # Multiple receipt PDFs
                for receipt_file in receipts:

                    process_bulk_pdf(
                        receipt_file,
                        "receipt",
                        tenants
                    )

                # -------------------------
                # Build tenant PDFs
                # -------------------------

                for key, docs in tenants.items():

                    writer = PdfWriter()

                    # ORDER REQUIRED
                    ordered_docs = [
                        "statement",
                        "invoice",
                        "water",
                        "receipt"
                    ]

                    for doc_type in ordered_docs:

                        for page in docs.get(doc_type, []):

                            writer.add_page(page)

                    clean_key = clean_text(key)

                    park = clean_text(
                        docs.get("park", "UNKNOWN")
                    )

                    godowns = clean_text(
                        docs.get("godowns", "")
                    )

                    date = clean_text(
                        docs.get(
                            "date",
                            "UNKNOWN_DATE"
                        )
                    )

                    park_dir = os.path.join(
                        output,
                        park
                    )

                    os.makedirs(
                        park_dir,
                        exist_ok=True
                    )

                    filename = (
                        f"{clean_key} "
                        f"{godowns} - "
                        f"{date}.pdf"
                    )

                    path = os.path.join(
                        park_dir,
                        filename
                    )

                    with open(path, "wb") as f:

                        writer.write(f)

                # -------------------------
                # Create ZIP
                # -------------------------

                zip_path = os.path.join(
                    tmp,
                    "tenant_pdfs.zip"
                )

                with zipfile.ZipFile(
                    zip_path,
                    "w",
                    zipfile.ZIP_DEFLATED
                ) as z:

                    for root, _, files in os.walk(output):

                        for file_name in files:

                            full_path = os.path.join(
                                root,
                                file_name
                            )

                            archive_name = os.path.relpath(
                                full_path,
                                output
                            )

                            z.write(
                                full_path,
                                archive_name
                            )

                with open(zip_path, "rb") as f:

                    st.success(
                        f"Generated {len(tenants)} tenant PDFs."
                    )

                    st.download_button(
                        label="Download ZIP",
                        data=f,
                        file_name="tenant_pdfs.zip",
                        mime="application/zip"
                    )
