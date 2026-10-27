"""
The catalogue of CRM capabilities and the default role-permission matrix
(Phase 1 plan, section 4).

Capabilities are created in the database automatically after every
`migrate`. Default role assignments are applied only when a capability is
first created, so changes the System Administrator makes later in
Roles & Limits are never overwritten.

Record-level rules apply on top: Sales Engineers see own/assigned records,
Sales Coordinators also see their linked team members' records (data scope).

Role codes
    ADMIN       System Administrator
    DIRECTOR    Sales Director
    ACCOUNTS    Accounts
    ENGINEER    Sales Engineer
    COORDINATOR Sales Coordinator
"""

ADMIN = "ADMIN"
DIRECTOR = "DIRECTOR"
ACCOUNTS = "ACCOUNTS"
ENGINEER = "ENGINEER"
COORDINATOR = "COORDINATOR"

ALL = [ADMIN, DIRECTOR, ACCOUNTS, ENGINEER, COORDINATOR]
SALES = [ADMIN, DIRECTOR, ENGINEER, COORDINATOR]
MGMT = [ADMIN, DIRECTOR]

# code, module, label, roles that receive it by default
CAPABILITIES = [
    # ---- dashboard
    ("dashboard.view", "Dashboard", "View dashboard", ALL),
    # ---- customers
    ("customers.view", "Customers", "Open customers", ALL),
    ("customers.create", "Customers", "Add customers and contacts", SALES),
    ("customers.edit", "Customers", "Edit customers and contacts", SALES),
    ("customers.archive", "Customers", "Archive and restore customers", MGMT),
    ("customers.delete", "Customers", "Delete customers that have no linked records", [ADMIN]),
    ("records.assign", "Customers", "Assign customers, visits, opportunities and tasks to other employees",
     [ADMIN, DIRECTOR, COORDINATOR]),
    # ---- leads
    ("leads.view", "Leads", "Open leads", SALES),
    ("leads.create", "Leads", "Register leads", SALES),
    ("leads.edit", "Leads", "Edit leads and move stages", SALES),
    ("leads.assign", "Leads", "Assign and reassign leads", [ADMIN, DIRECTOR, COORDINATOR]),
    ("leads.convert", "Leads", "Convert leads into customers and opportunities", SALES),
    ("leads.archive", "Leads", "Archive and restore leads", [ADMIN, DIRECTOR, COORDINATOR]),
    # ---- visits
    ("visits.view", "Customer visits", "Open customer visits", SALES),
    ("visits.create", "Customer visits", "Schedule visits", SALES),
    ("visits.edit", "Customer visits", "Edit, complete, reschedule and cancel visits", SALES),
    # ---- pipeline and projects
    ("pipeline.view", "Sales pipeline", "Open sales pipeline", SALES),
    ("pipeline.edit", "Sales pipeline", "Create and edit opportunities, move stages", [ADMIN, DIRECTOR, ENGINEER]),
    ("pipeline.archive", "Sales pipeline", "Archive and restore opportunities", MGMT),
    ("projects.view", "Projects", "Open projects", ALL),
    ("projects.edit", "Projects", "Create and edit delivery projects", SALES),
    # ---- quotations
    ("quotations.view", "Quotations", "Open quotations", SALES),
    ("quotations.edit", "Quotations", "Prepare and revise quotations", SALES),
    ("quotations.submit", "Quotations", "Submit quotations for approval, send, record customer response", SALES),
    ("quotations.approve", "Quotations", "Approve or reject quotations", MGMT),
    ("quotations.convert", "Quotations", "Create sales orders from accepted quotations", SALES),
    # ---- orders
    ("orders.view", "Sales orders", "Open sales orders", ALL),
    ("orders.edit", "Sales orders", "Update order progress, references and notes", SALES),
    ("orders.confirm", "Sales orders", "Confirm or cancel sales orders", MGMT),
    # ---- invoicing and collections
    ("invoices.view", "Invoices", "Open invoices", ALL),
    ("invoices.manage", "Invoices", "Create, issue, dispute and cancel invoices", [ADMIN, ACCOUNTS]),
    ("collections.view", "Collections", "Open collections and receivables", [ADMIN, DIRECTOR, ACCOUNTS]),
    ("payments.manage", "Collections", "Record, allocate and reverse payments", [ADMIN, ACCOUNTS]),
    ("statements.view", "Collections", "Generate statements of account", [ADMIN, DIRECTOR, ACCOUNTS, ENGINEER]),
    # ---- targets
    ("targets.view", "Targets & KPIs", "Open targets and KPIs", ALL),
    ("targets.manage", "Targets & KPIs", "Set targets and KPI definitions", MGMT),
    ("team.view", "Team", "See team-wide performance and rankings", MGMT),
    # ---- tasks and communications
    ("tasks.view", "Tasks", "Open tasks and follow-ups", ALL),
    ("tasks.create", "Tasks", "Create tasks and comment", ALL),
    ("communications.view", "Communication history", "Open communication history", ALL),
    ("communications.create", "Communication history", "Log calls, emails, meetings and messages", ALL),
    ("communications.delete", "Communication history", "Delete communication records", [ADMIN]),
    # ---- documents
    ("documents.view", "Documents", "Open documents", ALL),
    ("documents.upload", "Documents", "Upload and replace documents", ALL),
    ("documents.delete", "Documents", "Archive and delete documents", [ADMIN]),
    # ---- reports
    ("reports.view", "Reports", "Open reports", ALL),
    ("reports.sales", "Reports", "Sales, lead, quotation and order reports", SALES),
    ("reports.operational", "Reports", "Visit, task and follow-up reports", SALES),
    ("reports.customers", "Reports", "Customer reports", ALL),
    ("reports.financial", "Reports", "Invoice, collection and receivable reports", [ADMIN, DIRECTOR, ACCOUNTS]),
    # ---- notifications, import / export
    ("notifications.view", "Notifications", "Open notifications", ALL),
    ("data.import", "Import / export", "Import customers and leads", [ADMIN, DIRECTOR, COORDINATOR]),
    ("data.export", "Import / export", "Export to Excel and CSV", ALL),
    # ---- administration
    ("users.manage", "Administration", "Manage user accounts", [ADMIN]),
    ("roles.manage", "Administration", "Change role permissions and account limits", [ADMIN]),
    ("settings.manage", "Administration", "Change system settings", [ADMIN]),
    ("audit.view", "Administration", "View audit log", [ADMIN]),
]

# code, name, maximum accounts, data scope, description
ROLES = [
    (ADMIN, "System Administrator", 1, "all", "Complete system administration and configuration"),
    (DIRECTOR, "Sales Director", 2, "all", "Sales oversight, approvals, targets, forecasting and reports"),
    (ACCOUNTS, "Accounts", 2, "all", "Invoicing, collections, payment tracking and financial reports"),
    (ENGINEER, "Sales Engineer", 2, "own", "Leads, customer visits, projects, quotations and sales activities"),
    (COORDINATOR, "Sales Coordinator", 3, "team",
     "Lead allocation, scheduling, documentation, coordination and follow-ups"),
]
