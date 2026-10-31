# Sales flow update — meetings, customer-first leads, company history (v4)

## What changed

| Area | Change |
|---|---|
| Leads | Step 1 of **Add lead** is the customer: an existing one (searchable, limited to the user's scope) or a new one created with the lead (status *Prospect*; look-alike customers must be confirmed). **Add lead** on a customer page preselects it. The customer is locked once the lead has meetings or is in the pipeline. |
| Meetings (new) | **Add meeting** on leads and opportunities: date, time, type (in person / online / phone), location, attendees, held by, summary, points discussed, next action, next follow-up. Future dates are refused (plan them as visits); the follow-up cannot be before the meeting. The latest meeting updates the lead / opportunity follow-up date and the last-contact date, and writes to the activity timeline. Edits and deletions are in the Audit Log. |
| Move to Sales Pipeline | Replaces "Convert". A customer-first lead only asks for the opportunity (title required). Leads without a customer (old or imported) still choose / create the customer here. "Converted" now means *moved to the pipeline* (`converted_at`), not "has a customer". |
| Opportunity page | Steps bar (customer & lead → meetings → quotation → approval → customer answer → won/lost); meetings panel with *before the pipeline / in the pipeline* counts. |
| Lists | **Meetings** column on Leads and Opportunities; Opportunities also show the next follow-up. Lead filter "In sales pipeline". |
| Company history (new) | Dashboard box **View as a company**, menu **Company History**, button on the customer page. Summary counts, meetings per won deal, one block per sales journey, all meetings, full timeline. Scoped by role. |
| Elsewhere | Team Calendar shows recorded meetings; Employee Performance and the Owner Dashboard count *meetings held*; `remove_demo_data` removes demo meetings; demo data includes three meetings. |

## Database

One new table (`meetings_meeting`, migration `meetings.0001_initial`). No existing column changes, no data is
rewritten. Rolling back to the previous version leaves the table unused and was rehearsed without errors.

## Tests run for this version

- 248 automated tests on SQLite and on PostgreSQL 16 (15 new for this update).
- Every page reachable from the menu opened for all six demo roles (1,706 pages, 0 errors, 0 forbidden links).
- Browser checks (Chromium): v4 flow 34/34, v3 66/66, enhancement 62/62, smoke 77/77 — desktop and phone width.
- Upgrade from the previous version on PostgreSQL with data, then crawl: 0 errors. Rollback (previous code on the
  upgraded database): 0 errors.
- Production build (`build.sh` with production settings, Python 3.12) and a crawl under production settings.
