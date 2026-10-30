# Technoflow CRM — User Manual

This manual explains the CRM by task. Each role sees only the menus and records it is allowed to use; if a
button described here is missing, your role does not have that permission — ask the System Administrator.

## Contents

1. [Signing in](#1-signing-in)
2. [The screen](#2-the-screen)
3. [What each role does](#3-what-each-role-does)
4. [The sales workflow, step by step](#4-the-sales-workflow-step-by-step)
5. [Module reference](#5-module-reference)
6. [Reports, exports and import](#6-reports-exports-and-import)
7. [Good habits](#7-good-habits)
8. [Employee Performance and Daily Reports](#8-employee-performance-and-daily-reports)
9. [Lead categories, uploaded quotations and the Owner pages](#9-lead-categories-uploaded-quotations-and-the-owner-pages)

---

## 1. Signing in

- Use the username and temporary password from the System Administrator. At first sign-in you must choose
  a new password (10+ characters, not a common password, not only digits).
- After 5 wrong passwords your account is locked for 30 minutes (only for your username from that
  computer). The System Administrator can unlock it earlier.
- You are signed out after 60 minutes without activity.
- **Forgot your password?** Use the link on the sign-in page (needs e-mail to be set up) or ask the System
  Administrator for a temporary password.
- **Two-step sign-in (recommended)**: your name (top right) → **Two-step sign-in**. Scan the QR code with an
  authenticator app (Microsoft Authenticator, Google Authenticator, Authy), enter the 6-digit code, and from
  then on each sign-in asks for a code. Lost your phone? The System Administrator can reset it.

## 2. The screen

- **Left menu**: your modules. On a phone, open it with the ☰ button.
- **Search box** (top): searches customers (including contact names), leads, opportunities, projects,
  quotations, sales orders, invoices and tasks you are allowed to see.
- **Bell**: your latest notifications; the number is unread ones. **Notification preferences** (in your name
  menu) chooses which notifications you get in the CRM and by e-mail.
- **Lists** have filters, sorting (click a column heading) and, if your role allows, **Export** to Excel/CSV.
- Every record page shows a **timeline** of what happened to it, and a **Documents** panel.

## 3. What each role does

| Role | Main work |
| --- | --- |
| **System Administrator** | Users, roles and limits, settings (company, approvals, tax, stages, numbering, lists), audit log, import, everything else |
| **Sales Director** | Sees all sales records; approves quotations; confirms sales orders; sets targets and KPI weights; team dashboards and reports |
| **Accounts** | Invoices, payments, allocations, reversals, statements, collections, financial reports |
| **Sales Engineer** | Own leads, customers, visits, opportunities, quotations; follow-ups; own targets |
| **Sales Coordinator** | Supports linked engineers: schedules visits, prepares quotations, keeps records and follow-ups up to date |

## 4. The sales workflow, step by step

```text
Lead → (qualify) → Convert → Customer + Opportunity → Quotation → Submit → Approval
     → Sent → Accepted → Sales order → Milestones → Confirm → Invoices → Payments → Statement
```

1. **Record the enquiry as a lead** — Leads → **New lead**. Title, company, contact, source, estimated value.
   The CRM warns if a similar lead or customer already exists.
2. **Work the lead** — move it through the stages (Leads → **Kanban**: drag the card, or use its *Move to…*
   list). Log calls and meetings in **Communication History**; plan visits in **Customer Visits**.
   *Lost* needs a reason.
3. **Convert** — on the lead page, **Convert**. Link it to an existing customer or create a new one
   (the CRM shows look-alike customers first), and optionally create a sales **opportunity**.
4. **Opportunity** — Sales Pipeline. Keep the stage, value, probability and expected closing date current;
   these drive the forecast.
5. **Quotation** — on the opportunity, **Create quotation**. Add lines (description, quantity, unit, price,
   discount %, tax rate); totals update as you type. Add terms on the same page. **Save**.
6. **Submit for approval** — the CRM checks the approval rules (Settings). Within the limits it is approved
   automatically; otherwise Sales Directors are notified. **Nobody can approve their own quotation.**
   Rejected quotations come back with the Director's comments; edit and submit again.
7. **Send** — download the **PDF**, send it to the customer, then click **Mark as sent**.
8. **Customer answer** — **Record acceptance** (date, who accepted, PO reference) or **Record decline**
   (reason). To change an approved or sent quotation, click **Revise**: a new revision is created and the
   old one is kept unchanged.
9. **Sales order** — on the accepted quotation, **Create sales order**. Choose payment milestones
   (100 %, 50/50, 30/40/30, 30/70) — you can adjust them on the order. A **Sales Director confirms** the order;
   this marks the opportunity **Won** and tells Accounts.
10. **Invoices** (Accounts) — on the order, **Create invoice** for each milestone. Check it, then **Issue**:
    the invoice gets its number, cannot be edited any more, and the PDF is ready. The CRM refuses to invoice
    more than the order total.
11. **Payments** (Accounts) — Collections → **Record payment**. Enter the amount and allocate it to one or more
    open invoices; anything left over stays as customer credit and can be allocated later from the payment
    page. Wrong payment? **Reverse** it on the payment page (payments are never deleted).
12. **Follow up** — Collections shows overdue invoices by age; **Statement** on the customer shows every
    invoice and payment with a running balance (PDF/Excel).

## 5. Module reference

### Customers
New / edit / archive; contacts; 360° page with leads, opportunities, quotations, orders, invoices (if
allowed), visits, tasks, communications, documents and the timeline. The same TRN cannot be used twice;
other look-alikes (name, e-mail, phone) are warnings you must confirm. Archive instead of delete: only
customers without any linked records can be deleted.

### Leads
List and Kanban. Assign to an engineer/coordinator (needs permission; the new owner is notified).
Stages are set by the System Administrator; *Won* and *Lost* are fixed.

### Customer Visits
List, month **Calendar** and **Week** schedule (filter by employee). Schedule → Confirm → **Complete**
(meeting notes required; can create a follow-up task, update the opportunity and book the next visit).
Reschedule and Cancel keep the history. Missed visits (date passed, not completed) are highlighted.

### Sales Pipeline and Projects
List with totals, Kanban by stage, and **Forecast** (weighted value by expected closing month).
Projects are usually created from a confirmed order (**Create project** on the order) and track progress.

### Quotations
See section 4. Status filter "submitted" is the Director's approval queue; the dashboard lists it too.
Quotations past their expiry date are marked *Expired* automatically; you are warned a few days before.

**The printed quotation** follows Technoflow's standard format: (1) cover letter, (2) price schedule with
Sl No. / Part No. / Item description / Qty / Unit price / Total price, the total and the amount in words,
(3) commercial terms and conditions. Every section is edited on the quotation's edit page while it is a draft:
- *Cover letter*: customer name and address as printed, K/Attn, subject, project, consultant, letter text,
  closing, signatory name and designation. Empty name / address / attention / project use the customer and
  opportunity details.
- *Price schedule*: manufacturer line, note, sales engineer, sales in charge, approved by; line items with
  part numbers (**Add line** / tick **Remove**). Totals, VAT and the amount in words are calculated automatically.
- *Commercial terms and conditions*: a table of headings and texts, pre-filled from the company template;
  **Add term**, edit or tick **Remove**. In texts, a blank line starts a new paragraph and `**text**` is bold.

**Save draft**, **Save and keep editing** or **Save and preview**. On the quotation page, **Preview** shows the
PDF, **PDF** downloads it and **Word** downloads an editable .docx. Both always contain the latest saved data.
Drafts are marked "DRAFT — NOT APPROVED". The first issue prints as *Revision Number 0* (Rev 1 in the CRM),
the next revision as 1, and so on.

The company-wide wording (letterhead line, Arabic name, default letter, note, default terms and footer) is
in **Settings → Quotation template** (System Administrator).

### Sales Orders
Created only from accepted quotations. Draft → Confirmed → In progress → Partially completed → Completed (or Cancelled with a
reason by a Director, only while no invoice is issued). Order value is counted **excluding VAT** in "Orders booked".

### Invoices and Collections
Draft → Issued → Partially paid → Paid (or Cancelled — only when nothing is paid). **Dispute** flags an
invoice without changing its amounts. Collections: ageing buckets (current, 1–30, 31–60, 61–90, 90+ days),
overdue list, payments list.

### Targets & KPIs
Directors set monthly or quarterly targets per employee (Targets & KPIs → **Set targets**) for: orders booked,
invoiced, collected, quotation value, leads created, visits completed, new customers, opportunities won,
lead conversion % and follow-up completion %. The scorecard shows target, actual, achievement % and the
weighted score with its rating (Excellent / Good / Satisfactory / Needs improvement).

### Tasks & Follow-ups
Your open tasks first (*Mine*, *Team*, *Overdue*), calendar view, comments, status changes. Tasks can be
linked to a customer, lead, visit, opportunity, quotation or invoice.

### Communication History
Log calls, e-mails, WhatsApp messages, meetings and site visits manually, with outcome and next action;
optionally create a follow-up task at the same time. (The CRM does not read your mailbox or WhatsApp.)

### Documents
Upload on any customer, lead, opportunity, quotation, order, invoice, project, visit or communication.
Allowed types are set by the System Administrator (PDF, Office files, images…); programs and web pages are
always refused. Uploading a new version keeps the old one. Files can only be downloaded by people who can
see the record.

### Dashboard
Cards and charts for your role and data scope. Choose the period and (if you see a team) an employee.
Click any card, bar or point to open the records behind the number.

## 6. Reports, exports and import

- **Reports** menu: 44 reports in 8 groups (customers, leads, sales, visits, quotations, orders, financial,
  employees). Each has period and employee filters and **Excel / CSV / PDF** buttons (if your role may export).
  Figures come from the same calculations as the dashboard, so they always agree.
- The four money measures are kept separate on purpose:
  *Quotations issued* (sent to customers) · *Orders booked* (confirmed orders, excl. VAT) ·
  *Invoiced* (issued invoices, incl. VAT) · *Collected* (payments received, net of reversals).
- **Import from Excel** (menu): choose what you are importing — customers, leads, customer visits,
  follow-ups/tasks, or opportunities and completed sales.
  1. Download the template for that type. Its *Instructions* sheet lists the allowed values.
  2. Fill it in and upload it.
  3. Check the preview. Every row shows **New**, **Update**, **Duplicate** or **Error**, with the reason and the
     Excel row number.
  4. Click **Import**. Nothing is saved before you confirm, and if anything fails, nothing is saved at all.
  - Salespeople import their own records. Managers and administrators name the employee in the file.
  - Dates in the file (date received, visit date, closing date) are kept.
  - Uploading the same file again adds nothing.
  - A deal becomes *Won* only when its Status / stage column says Won.
  - Rows that were not imported can be downloaded as a CSV, with the reason, to fix and upload again.

## 7. Good habits

- Update the next follow-up date whenever you speak to a customer — reminders and the dashboard depend on it.
- Use **Revise**, not a new quotation, when the customer asks for changes: the history stays in one place.
- Never share your password; turn on two-step sign-in.
- If something looks wrong, note the record number and tell the System Administrator — the audit log shows
  who changed what and when.

## 8. Employee Performance and Daily Reports

**Employee Performance** (menu → Work):
- **Managers** see everyone they manage: leads, visits, quotations, deals won and lost, won value, monthly
  target progress, pending follow-ups and overdue tasks.
  - Choose a period: *Today, Yesterday, This week, Last week, This month, Last month* or your own dates.
  - Filter by employee, designation, department, reporting manager or status, and sort by any column.
  - Click a name to open that person's dashboard. Excel/CSV export follows your export permission.
- **Salespeople** see only their own dashboard.
- Figures marked **now** show today's situation and do not change with the period.

**Daily Reports** (menu → Work):
- Click **Write today's report**. Fill in what you did, then add activity lines if you like.
- Click **Submit**, or **Save as draft**. Drafts are private.
- You can change a submitted report until your manager marks it **reviewed**. Every change is recorded and
  shown under *Change history*.
- Reports are **self-reported**. Each report page shows them next to the figures the CRM recorded that
  day, so the two can be compared.
- Managers see a summary for the week or month, showing reports submitted and working days missing.

## 9. Lead categories, uploaded quotations and the Owner pages

**Leads:**
- Every new lead needs a **category**: click **Job in Hand**, **Tender** or **Purchase Enquiry** at the top
  of the form.
- Estimated value is optional.
- The lead page shows who created the lead and who is responsible. **Change history** lists every change.
- Filter the Leads list by category, status, source, employee and dates. The **Dashboard** tab shows the same
  as charts.

**Opportunities:**
- The **Opportunities** menu lists every opportunity; the **Sales Pipeline** menu shows the board and forecast.
- On a converted lead, click **Create opportunity**: the details are copied from the lead.
- A lead can have only one active opportunity.

**Quotations:**
1. Prepare the quotation in your quotation system.
2. In the CRM, click **Upload quotation**: choose the file and enter its number, date, value and customer
   (and lead / opportunity).
3. For a change, open the quotation and click **Upload revision**. It becomes R1, R2 …, and older revisions
   stay downloadable in **Revision history**.
4. Click **Mark as final** on the agreed version.
5. **Submit for approval** sends it to the Owner's Pending Approvals.

**Owner:**
- **Owner Dashboard** shows the whole business, with targets per month, quarter or year.
- **Pending Approvals** has Approve / Reject with comments.
- **Team Calendar** shows everyone's visits, meetings, follow-ups, tasks and deadlines.
- **Modules & Approvals** turns Finance on or off and lets the Sales Director approve as backup.

