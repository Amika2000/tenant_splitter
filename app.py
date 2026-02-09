import streamlit as st
import pdfplumber
from pypdf import PdfReader, PdfWriter
from collections import defaultdict
import os, re, shutil
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
invoices   = st.file_uploader("Upload Invoices PDF", type="pdf")
receipts   = st.file_uploader("Upload Receipts PDF", type="pdf")
water      = st.file_uploader("Upload Water PDF (optional)", type="pdf")

# -----------------------------
# Core logic (same as yours)
# -----------------------------

def normalize(name):
    name = name.upper()
    name = re.sub(r"\s+", " ", name)
    return name.strip()

def first_two_words(name):
    return " ".join(normalize(name).split()[:2])

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
                if re.fullmatch(r"\d{2}/\d{2}/\d{4}", up):
                    continue
                if "PO BOX" in up or "P O BOX" in up:
                    continue
                if re.search(r"\d", up):
                    m = re.search(r"\d.*", up)
                    return m.group().strip()
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
            return lines[i+1]
        if "received from" in low:
            return lines[i+1]
        if low.endswith(" statement"):
            return lines[i].replace("Statement", "").strip()
    return None

def process_bulk_pdf(file, doc_type, tenants):
    with pdfplumber.open(file) as pdf:
        reader = PdfReader(file)
        current_key = None
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            raw = extract_tenant_name(text)
            if raw:
                current_key = first_two_words(raw)
                if doc_type == "statement":
                    tenants[current_key]["park"] = extract_park(text)
                    tenants[current_key]["godowns"] = extract_godowns(text, raw)
                    tenants[current_key]["date"] = extract_month_year(text)
            if current_key:
                tenants[current_key][doc_type].append(reader.pages[i])

# -----------------------------
# Run
# -----------------------------

if st.button("Process PDFs") and statements and invoices and receipts:

    with tempfile.TemporaryDirectory() as tmp:
        output = os.path.join(tmp, "output")
        os.makedirs(output)

        tenants = defaultdict(lambda: defaultdict(list))

        process_bulk_pdf(statements, "statement", tenants)
        process_bulk_pdf(invoices, "invoice", tenants)
        process_bulk_pdf(receipts, "receipt", tenants)
        if water:
            process_bulk_pdf(water, "water", tenants)

        for key, docs in tenants.items():
            writer = PdfWriter()
            for doc in ["statement","invoice","receipt","water"]:
                for p in docs.get(doc, []):
                    writer.add_page(p)

            park = docs.get("park","UNKNOWN")
            godowns = docs.get("godowns","")
            date = docs.get("date","")

            park_dir = os.path.join(output, park)
            os.makedirs(park_dir, exist_ok=True)

            filename = f"{key} {godowns} - {date}.pdf"
            path = os.path.join(park_dir, filename)

            with open(path,"wb") as f:
                writer.write(f)

        zip_path = os.path.join(tmp, "tenant_pdfs.zip")
        with zipfile.ZipFile(zip_path, "w") as z:
            for root, _, files in os.walk(output):
                for f in files:
                    full = os.path.join(root,f)
                    z.write(full, arcname=os.path.relpath(full, output))

        with open(zip_path, "rb") as f:
            st.download_button(
                "Download ZIP",
                f,
                file_name="tenant_pdfs.zip",
                mime="application/zip"
            )
