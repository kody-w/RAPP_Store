"""
PDF Processor Agent - Comprehensive PDF manipulation toolkit

Part of the RAPP Store - https://github.com/kody-w/RAPP_Store
"""

from agents.basic_agent import BasicAgent
import logging


class PdfProcessorAgent(BasicAgent):
    """
    Comprehensive PDF manipulation toolkit for extracting text, merging,
    splitting, filling forms, and adding watermarks to PDF documents.
    """

    def __init__(self):
        self.name = 'PdfProcessor'
        self.metadata = {
            "name": self.name,
            "description": "Comprehensive PDF manipulation toolkit - extract text and tables, merge multiple PDFs, split by page, fill forms programmatically, add watermarks and annotations. Use this agent when you need to work with PDF files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform: 'extract_text' (get text from PDF), 'extract_tables' (get tables as structured data), 'merge' (combine PDFs), 'split' (split into pages), 'get_metadata' (get PDF info), 'fill_form' (fill form fields), 'add_watermark' (add watermark), 'get_guidance' (get implementation guidance)",
                        "enum": ["extract_text", "extract_tables", "merge", "split", "get_metadata", "fill_form", "add_watermark", "get_guidance"]
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to the PDF file to process"
                    },
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of PDF file paths (for merge action)"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path for the result"
                    },
                    "page_numbers": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Specific pages to extract (1-indexed)"
                    },
                    "form_data": {
                        "type": "object",
                        "description": "Dictionary of form field names to values for fill_form action"
                    },
                    "watermark_text": {
                        "type": "string",
                        "description": "Text to use as watermark"
                    },
                    "topic": {
                        "type": "string",
                        "description": "Specific topic for get_guidance action (e.g., 'ocr', 'tables', 'forms')"
                    }
                },
                "required": ["action"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get('action')

        try:
            if action == 'extract_text':
                return self._extract_text(kwargs)
            elif action == 'extract_tables':
                return self._extract_tables(kwargs)
            elif action == 'merge':
                return self._merge_pdfs(kwargs)
            elif action == 'split':
                return self._split_pdf(kwargs)
            elif action == 'get_metadata':
                return self._get_metadata(kwargs)
            elif action == 'fill_form':
                return self._fill_form_guidance(kwargs)
            elif action == 'add_watermark':
                return self._add_watermark_guidance(kwargs)
            elif action == 'get_guidance':
                return self._get_guidance(kwargs)
            else:
                return f"Error: Unknown action '{action}'"
        except Exception as e:
            logging.error(f"Error in PdfProcessor: {str(e)}")
            return f"Error: {str(e)}"

    def _extract_text(self, params):
        """Extract text from PDF"""
        file_path = params.get('file_path')
        if not file_path:
            return "Error: file_path is required for extract_text action"

        return f"""📄 PDF Text Extraction

**File:** {file_path}

**Code to Extract Text:**

```python
from pypdf import PdfReader

# Read the PDF
reader = PdfReader("{file_path}")
print(f"Pages: {{len(reader.pages)}}")

# Extract text from all pages
text = ""
for i, page in enumerate(reader.pages):
    page_text = page.extract_text()
    text += f"\\n--- Page {{i+1}} ---\\n{{page_text}}"

print(text)
```

**Alternative with pdfplumber (better layout preservation):**

```python
import pdfplumber

with pdfplumber.open("{file_path}") as pdf:
    for i, page in enumerate(pdf.pages):
        text = page.extract_text()
        print(f"--- Page {{i+1}} ---")
        print(text)
```

**For scanned PDFs (OCR required):**

```python
import pytesseract
from pdf2image import convert_from_path

images = convert_from_path("{file_path}")
for i, image in enumerate(images):
    text = pytesseract.image_to_string(image)
    print(f"--- Page {{i+1}} ---")
    print(text)
```
"""

    def _extract_tables(self, params):
        """Extract tables from PDF"""
        file_path = params.get('file_path')
        if not file_path:
            return "Error: file_path is required for extract_tables action"

        return f"""📊 PDF Table Extraction

**File:** {file_path}

**Code to Extract Tables:**

```python
import pdfplumber
import pandas as pd

with pdfplumber.open("{file_path}") as pdf:
    all_tables = []

    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()

        for j, table in enumerate(tables):
            if table:
                # Convert to DataFrame
                df = pd.DataFrame(table[1:], columns=table[0])
                all_tables.append(df)
                print(f"Table {{j+1}} on page {{i+1}}:")
                print(df)
                print()

# Optionally combine all tables
if all_tables:
    combined = pd.concat(all_tables, ignore_index=True)
    combined.to_excel("extracted_tables.xlsx", index=False)
```

**With custom table settings:**

```python
table_settings = {{
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 3,
}}

with pdfplumber.open("{file_path}") as pdf:
    page = pdf.pages[0]
    table = page.extract_table(table_settings)
```
"""

    def _merge_pdfs(self, params):
        """Merge multiple PDFs"""
        file_paths = params.get('file_paths', [])
        output_path = params.get('output_path', 'merged.pdf')

        if not file_paths:
            return "Error: file_paths is required for merge action"

        files_str = '", "'.join(file_paths)

        return f"""📑 PDF Merge

**Files to merge:** {len(file_paths)} files
**Output:** {output_path}

**Code to Merge PDFs:**

```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()

files = ["{files_str}"]

for pdf_file in files:
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

with open("{output_path}", "wb") as output:
    writer.write(output)

print(f"Merged {{len(files)}} PDFs into {output_path}")
```

**With page selection:**

```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()

# Add specific pages from each file
configs = [
    ("{file_paths[0] if file_paths else 'file1.pdf'}", [1, 2, 3]),  # Pages 1-3
    ("{file_paths[1] if len(file_paths) > 1 else 'file2.pdf'}", None),  # All pages
]

for pdf_file, pages in configs:
    reader = PdfReader(pdf_file)
    if pages:
        for page_num in pages:
            writer.add_page(reader.pages[page_num - 1])
    else:
        for page in reader.pages:
            writer.add_page(page)

with open("{output_path}", "wb") as output:
    writer.write(output)
```
"""

    def _split_pdf(self, params):
        """Split PDF into pages"""
        file_path = params.get('file_path')
        page_numbers = params.get('page_numbers')

        if not file_path:
            return "Error: file_path is required for split action"

        return f"""✂️ PDF Split

**File:** {file_path}
**Pages:** {page_numbers if page_numbers else 'All pages'}

**Code to Split PDF:**

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("{file_path}")

# Split into individual pages
for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)

    output_path = f"page_{{i+1}}.pdf"
    with open(output_path, "wb") as output:
        writer.write(output)

    print(f"Created {{output_path}}")
```

**Extract specific pages:**

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("{file_path}")
writer = PdfWriter()

pages_to_extract = {page_numbers if page_numbers else [1, 2, 3]}  # 1-indexed

for page_num in pages_to_extract:
    writer.add_page(reader.pages[page_num - 1])

with open("extracted_pages.pdf", "wb") as output:
    writer.write(output)
```

**Split by page ranges:**

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("{file_path}")

# Define ranges
ranges = [
    (1, 5, "part1.pdf"),    # Pages 1-5
    (6, 10, "part2.pdf"),   # Pages 6-10
    (11, None, "part3.pdf") # Pages 11 to end
]

for start, end, output_name in ranges:
    writer = PdfWriter()
    end_page = end if end else len(reader.pages)

    for i in range(start - 1, end_page):
        writer.add_page(reader.pages[i])

    with open(output_name, "wb") as output:
        writer.write(output)
```
"""

    def _get_metadata(self, params):
        """Get PDF metadata"""
        file_path = params.get('file_path')
        if not file_path:
            return "Error: file_path is required for get_metadata action"

        return f"""📋 PDF Metadata

**File:** {file_path}

**Code to Get Metadata:**

```python
from pypdf import PdfReader

reader = PdfReader("{file_path}")

# Basic info
print(f"Number of pages: {{len(reader.pages)}}")

# Document metadata
meta = reader.metadata
if meta:
    print(f"Title: {{meta.title}}")
    print(f"Author: {{meta.author}}")
    print(f"Subject: {{meta.subject}}")
    print(f"Creator: {{meta.creator}}")
    print(f"Producer: {{meta.producer}}")
    print(f"Creation Date: {{meta.creation_date}}")
    print(f"Modification Date: {{meta.modification_date}}")

# Check for encryption
print(f"Is encrypted: {{reader.is_encrypted}}")

# Page dimensions
page = reader.pages[0]
print(f"Page size: {{page.mediabox.width}} x {{page.mediabox.height}}")
```

**Check for forms:**

```python
from pypdf import PdfReader

reader = PdfReader("{file_path}")

# Check for AcroForm
if reader.get_fields():
    print("This PDF has fillable form fields:")
    for field_name, field in reader.get_fields().items():
        print(f"  - {{field_name}}: {{field.get('/FT', 'Unknown type')}}")
else:
    print("No fillable form fields found")
```
"""

    def _fill_form_guidance(self, params):
        """Provide guidance for filling PDF forms"""
        file_path = params.get('file_path', 'form.pdf')
        form_data = params.get('form_data', {})

        return f"""📝 PDF Form Filling

**File:** {file_path}
**Form Data:** {form_data}

**Step 1: Discover Form Fields**

```python
from pypdf import PdfReader

reader = PdfReader("{file_path}")
fields = reader.get_fields()

if fields:
    print("Available form fields:")
    for name, field in fields.items():
        field_type = field.get('/FT', 'Unknown')
        value = field.get('/V', '')
        print(f"  {{name}}: type={{field_type}}, current={{value}}")
```

**Step 2: Fill the Form**

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("{file_path}")
writer = PdfWriter()

# Clone all pages
writer.append(reader)

# Fill form fields
form_data = {form_data if form_data else {"field_name": "value"}}

writer.update_page_form_field_values(
    writer.pages[0],
    form_data
)

with open("filled_form.pdf", "wb") as output:
    writer.write(output)
```

**For Complex Forms (with annotations):**

```python
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

reader = PdfReader("{file_path}")
writer = PdfWriter()
writer.append(reader)

# Access and modify annotations
page = writer.pages[0]
if "/Annots" in page:
    for annot in page["/Annots"]:
        obj = annot.get_object()
        if obj.get("/T"):
            field_name = str(obj["/T"])
            if field_name in form_data:
                obj.update({{
                    NameObject("/V"): TextStringObject(form_data[field_name])
                }})

with open("filled_form.pdf", "wb") as output:
    writer.write(output)
```
"""

    def _add_watermark_guidance(self, params):
        """Provide guidance for adding watermarks"""
        file_path = params.get('file_path', 'document.pdf')
        watermark_text = params.get('watermark_text', 'CONFIDENTIAL')

        return f"""💧 PDF Watermark

**File:** {file_path}
**Watermark:** {watermark_text}

**Method 1: Merge with Watermark PDF**

```python
from pypdf import PdfReader, PdfWriter

# First, create a watermark PDF (or use existing)
# Then merge:

document = PdfReader("{file_path}")
watermark = PdfReader("watermark.pdf")
watermark_page = watermark.pages[0]

writer = PdfWriter()

for page in document.pages:
    page.merge_page(watermark_page)
    writer.add_page(page)

with open("watermarked.pdf", "wb") as output:
    writer.write(output)
```

**Method 2: Create Watermark with ReportLab**

```python
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import Color
from pypdf import PdfReader, PdfWriter
import io

# Create watermark
packet = io.BytesIO()
c = canvas.Canvas(packet, pagesize=letter)
c.setFont("Helvetica", 60)
c.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.3))
c.saveState()
c.translate(300, 400)
c.rotate(45)
c.drawCentredString(0, 0, "{watermark_text}")
c.restoreState()
c.save()
packet.seek(0)

# Apply watermark
watermark = PdfReader(packet)
document = PdfReader("{file_path}")
writer = PdfWriter()

for page in document.pages:
    page.merge_page(watermark.pages[0])
    writer.add_page(page)

with open("watermarked.pdf", "wb") as output:
    writer.write(output)
```
"""

    def _get_guidance(self, params):
        """Get general PDF guidance"""
        topic = params.get('topic', 'general')

        guidance = {
            'general': """📚 PDF Processing Guide

**Recommended Libraries:**
- `pypdf` - Basic operations (read, write, merge, split)
- `pdfplumber` - Text and table extraction
- `reportlab` - Create PDFs from scratch
- `pytesseract` + `pdf2image` - OCR for scanned PDFs

**Install:**
```bash
pip install pypdf pdfplumber reportlab pytesseract pdf2image
```

**Quick Reference:**
| Task | Library | Key Function |
|------|---------|--------------|
| Read PDF | pypdf | `PdfReader()` |
| Extract text | pdfplumber | `page.extract_text()` |
| Extract tables | pdfplumber | `page.extract_tables()` |
| Merge PDFs | pypdf | `writer.add_page()` |
| Split PDF | pypdf | One page per writer |
| Create PDF | reportlab | `canvas.Canvas()` |
| OCR | pytesseract | `image_to_string()` |
| Fill forms | pypdf | `update_page_form_field_values()` |
""",
            'ocr': """🔍 OCR for Scanned PDFs

**Requirements:**
- Tesseract OCR installed on system
- Python packages: `pytesseract`, `pdf2image`

**Installation:**
```bash
# macOS
brew install tesseract poppler

# Ubuntu
sudo apt install tesseract-ocr poppler-utils

# Python
pip install pytesseract pdf2image
```

**Basic OCR:**
```python
import pytesseract
from pdf2image import convert_from_path

images = convert_from_path('scanned.pdf', dpi=300)

text = ""
for i, image in enumerate(images):
    page_text = pytesseract.image_to_string(image)
    text += f"\\n--- Page {i+1} ---\\n{page_text}"

print(text)
```
""",
            'tables': """📊 Table Extraction Tips

**Best Practices:**
1. Use `pdfplumber` for structured tables
2. Adjust table detection settings for complex layouts
3. Handle merged cells explicitly

**Custom Table Settings:**
```python
import pdfplumber

table_settings = {
    "vertical_strategy": "lines",      # or "text"
    "horizontal_strategy": "lines",    # or "text"
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "edge_min_length": 3,
    "min_words_vertical": 3,
    "min_words_horizontal": 1,
}

with pdfplumber.open('document.pdf') as pdf:
    page = pdf.pages[0]
    table = page.extract_table(table_settings)
```
"""
        }

        return guidance.get(topic, guidance['general'])
