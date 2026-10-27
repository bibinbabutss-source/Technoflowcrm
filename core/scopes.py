"""
Who "owns" each kind of record, for the role data scope.

A Sales Engineer (scope: own) sees a record when they appear in any of these
fields; a Sales Coordinator (scope: team) also sees records where one of their
linked team members appears. Roles with scope "all" see everything.

Keeping the list in one place means every page, search, export, report and
document download applies exactly the same rule.
"""
CUSTOMER_LINK = ("customer__assigned_engineer", "customer__assigned_coordinator")

OWNERS = {
    "customers.customer": ("assigned_engineer", "assigned_coordinator", "created_by"),
    "leads.lead": ("assigned_engineer", "assigned_coordinator", "created_by"),
    "sales.opportunity": ("assigned_engineer", "assigned_coordinator", "created_by"),
    "sales.project": ("project_manager", "created_by", *CUSTOMER_LINK),
    "visits.visit": ("assigned_to", "created_by", *CUSTOMER_LINK),
    "communications.communication": ("employee", "created_by", *CUSTOMER_LINK),
    "tasks.task": ("assigned_to", "created_by"),
    "quotations.quotation": ("salesperson", "created_by", *CUSTOMER_LINK),
    "orders.salesorder": ("assigned_to", "created_by", *CUSTOMER_LINK),
    "invoicing.invoice": ("created_by", "order__assigned_to", *CUSTOMER_LINK),
    "invoicing.payment": ("created_by", *CUSTOMER_LINK),
    "documents.document": ("uploaded_by", *CUSTOMER_LINK),
}


def owners(label):
    return OWNERS[label]
