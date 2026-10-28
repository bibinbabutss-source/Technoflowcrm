# Quotation format and logo update — 28-Oct-2026

This was a targeted update. Only the quotation document, the quotation edit page and the logo changed.
Dashboards, navigation, colours, other modules, roles and existing records are unchanged.
The project as it was before this update is kept as `technoflow_crm_backup_before_quotation_update.zip`.

## What changed

### 1. Quotation PDF in Technoflow's format
The PDF follows the sample quotation SQ/2026/0807. It has three parts:

1. **Cover letter**
   - date, customer name and address, K/Attn, subject, quote reference, project and revision number
   - the letter text and closing
   - the signatory line, with the designation on the left and "Authorised Signatory" on the right
   - the boxed area of the sample
2. **Price schedule**
   - The header repeats on every page: "PRICE SCHEDULE", Customer / Project / Consultant, Date / Currency
     (full name) / Quote No., the "MANUFACTURER" line and the column titles (Sl No., Part No., Item
     description, Qty, Unit price, Total price).
   - The note line and the Sales Engineer / Sales In Charge / Approved By block repeat on every page.
   - The last page has the TOTAL AMOUNT and the amount in words, e.g. "… DIRHAMS AND FOURTEEN FILS ONLY".
   - When VAT or a discount applies, SUB TOTAL, DISCOUNT and VAT rows are printed above the TOTAL AMOUNT.
   - A DISC. column appears only when a line has a discount.
3. **Commercial terms and conditions**
   - the page border and the two-column table of headings and texts

**Letterhead and footer (every page):**
- the official logo
- the line under the logo (AN ISO 9001:2015 COMPANY), the Arabic company name, the legal name and the TRN
- footer: "Technology at its best", the website, the business lines and the contact line

**Paging:** long descriptions and long terms continue onto the next page without overlapping or being cut.
The test with the 103 lines of the sample produced 11 pages with the same total, 795,493.14.

### 2. Everything editable in the CRM
- On the quotation edit page (drafts only, as before), you can edit:
  - customer name and address as printed, K/Attn, subject, project, consultant
  - cover-letter text, closing, signatory name and designation
  - manufacturer line, price-schedule note, sales engineer, sales in charge, approved by
  - line items with a **part number** (add or remove rows)
  - the **commercial terms table** (add, edit or remove rows)
  - scope of work, exclusions, notes and dates
- If you leave customer name, address, attention, project or sales engineer empty, the PDF uses the
  customer, opportunity and salesperson records.
- Totals, VAT and the amount in words are calculated by the server.
- New buttons: **Save and keep editing**, **Save and preview**. On the quotation page: **Preview**, **PDF**
  (download), **Word** (.docx).
- **Settings → Quotation template** (System Administrator) holds:
  - the company-wide letterhead line, Arabic name and footer
  - the default letter, closing, signatory designation and note
  - the default terms
  - Defaults are taken from the sample. New quotations copy the defaults; each quotation keeps its own text
    afterwards.
- **Revise** copies all of this, including terms and part numbers, into the new revision.

### 3. Editable Word export
The .docx has the same three parts:
- the logo and letterhead lines in the page header
- the footer
- the price table, whose column titles repeat on every page
- the terms table

It is meant for occasional manual edits. The PDF is the reference layout.

### 4. Logo
The uploaded logo image is used as supplied: no redrawing, recolouring or distortion. Only the empty white
margin was trimmed. The aspect ratio is 2.445 : 1.
- `static/img/technoflow-logo-full.png` (1533 × 627) — PDFs and Word
- `static/img/technoflow-logo.png` (480 × 196) — web pages
- `static/img/original/technoflow-logo-original.png` — the untouched upload

**Where the logo appears:**
- sign-in page
- top bar of every page
- browser tab icon
- quotation PDF (every page)
- quotation preview
- quotation Word file
- invoice, statement and report PDFs, through the shared PDF header

## Database changes (additive, no data changed)
Migration `quotations/0002`:
- new optional fields on quotation revisions (the document sections)
- `part_no` on quotation lines
- new tables `QuotationTerm` (terms rows) and `QuotationTemplate` (one row of company wording)

No existing record is modified or deleted. Quotations made before the update still print: empty
sections fall back to the customer and template, and their older payment / delivery / warranty / validity
texts become the terms table.

Permissions are unchanged:
- Editing needs `quotations.edit` and works only on drafts, as before.
- Viewing and downloading need `quotations.view`, with the usual record scope.
- The template needs `settings.manage`.

## Files changed or added
- `quotations/models.py`, `quotations/migrations/0002_*.py`
- `quotations/document.py` (new)
- `quotations/docx_export.py` (new)
- `quotations/templatetags/quotation_doc.py` (new)
- `quotations/forms.py`, `quotations/views.py`, `quotations/urls.py`, `quotations/services.py`
- `templates/quotations/pdf.html` (rewritten)
- `templates/quotations/edit.html`, `detail.html`
- `templates/quotations/preview.html` (new)
- `templates/quotations/template_settings.html` (new)
- `templates/quotations/_fieldset.html` (new)
- `templates/quotations/_term_row.html` (new)
- `templates/partials/lines_editor.html`, `line_row.html` — Part no. column appears only for quotation lines
- `templates/core/_settings_tabs.html` — new "Quotation template" tab
- `templates/pdf/base.html` — high-resolution logo
- `static/img/` (logo files), `static/fonts/DejaVuSans.ttf` (for the Arabic name)
- `requirements.txt` — `python-docx`
- `tests/test_quotation_document.py` (new), `tests/data/sample_quotation_items.json` (new)
- docs: this file, USER_MANUAL, ADMIN_GUIDE

## Tests run (actual results)
- **Automated tests:** 156 passed on SQLite and 156 passed on PostgreSQL 16. That is the 145 earlier tests,
  all still passing, plus 11 new quotation tests. The new tests cover:
  - creating a quotation with every section filled in
  - reopening the draft
  - adding and removing lines and terms
  - totals and VAT
  - Save and preview
  - PDF download containing the latest edits
  - a multi-page quotation with the sample's 103 lines, total 795,493.14 and the amount in words
  - long descriptions and long terms across pages
  - the Word export
  - revise copying sections, terms and part numbers
  - locked terms after submission
  - older quotations still printing
  - permissions
  - the template settings
  - the logo on the sign-in page, the dashboard and every PDF page
  - amount-in-words
- **Browser (Chromium):**
  - Quotation editor test, 8/8 passed: new quotation pre-filled with the 14 default terms, add a line, add
    and remove a term, Save and preview, PDF and Word downloads containing the edits, the edit page fits
    a phone screen, no JavaScript errors.
  - The full UI regression test (all 5 roles, desktop and phone) was run again: 77/77 passed.
- **Page check:** every page reachable for every role, with 0 server errors.
- **Visual check:** PDF pages rendered to images and compared side by side with the sample's pages.

## Limitations
- **PDF engine:** xhtml2pdf, chosen because it installs on Windows. Layout matches the sample closely but
  not pixel-for-pixel.
  - Fonts are Helvetica (the sample looks like Arial; they are almost identical).
  - Row heights differ slightly, so page breaks can fall on different lines than in the sample. The
    103-line sample prints on 11 pages, the same number as the original.
  - On the last page the TOTAL AMOUNT is printed inside the boxed area, right after the last line, not just
    below the box.
- **Not reproduced:**
  - The ISO 9001:2008 certification badge and the second logo variant on the terms pages, because those
    images were not supplied. The terms pages use the official logo.
  - The italic indented numbering in "Price terms": numbered lines print as normal text.
- **Revision numbering:** the first issue prints "Revision Number 0" as on the sample, while the CRM screen
  still calls it "Rev 1". File names use the printed number, e.g. `QT-2026-0011-Rev0.pdf`.
- **Quotation number style:** the CRM's numbering joins parts with "-" (e.g. `SQ-2026-0807`). The sample's
  `SQ/2026/0807` style with "/" would need a change to the numbering module, which was outside this
  update. The prefix itself (SQ) can be set in Settings → Document numbering.
- **Totals and VAT:** the sample's prices exclude VAT and show only the TOTAL AMOUNT. The CRM keeps VAT in
  the quotation so orders and invoices stay correct, and prints SUB TOTAL and VAT rows when VAT applies.
  To print a single total as in the sample, use the "Zero-rated" tax rate on the lines and keep the note
  that VAT applies.
- **Order lines:** part numbers stay on the quotation; they are not copied to order or invoice lines.
- **In-page preview:** the preview page shows the PDF in an embedded viewer, which some phones don't
  support (Download PDF works). The automated browser can't display PDFs, so the preview was verified by
  checking the page and the PDF response, not by looking at it.
- **Word export:** simpler layout than the PDF: no box borders on the cover page and no page border on
  the terms pages.
