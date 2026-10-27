# Technoflow CRM — Database

PostgreSQL in production (SQLite only for development and tests). Tables are created by Django migrations
(`python manage.py migrate`); never edit the structure by hand.

## Rules built into the data model

- **Money** is stored as `NUMERIC(14,2)` (Decimal), never floating point. All calculations go through
  `core/money.py`, and dashboards/reports through `reporting/metrics.py`, so figures are the same everywhere.
- **Quotation revisions** are separate rows. A submitted, approved or sent revision is locked: its lines and
  financial fields cannot be changed (enforced in the model `save()`); changes create a new revision.
- **Invoices** get their number only when issued, from `NumberSequence` with a row lock (no gaps, no duplicates).
  Issued invoices' amounts are locked.
- **Payments are never updated or deleted.** A reversal is a new payment row with `is_reversal=True` pointing at
  the original; allocations are `PaymentAllocation` rows (a database constraint forbids zero amounts).
- **Audit log** (`core_auditlog`) is append-only and records changed fields with before/after values for every
  tracked business table; `core_activity` is the business timeline shown on record pages.
- **Deletes** use `PROTECT` on business links: a customer with quotations, orders or invoices cannot be deleted
  (archive it instead).
- **Documents** keep only metadata in the database; files are stored in the private `MEDIA_ROOT` folder under
  random names, with a SHA-256 checksum. New versions point to the previous one (`previous`, `is_current`).
- **Ownership / scope**: records carry `assigned_engineer` / `assigned_coordinator` / `salesperson` /
  `assigned_to`; the role's data scope filters on these fields everywhere.
- Every business table has `created_at`, `created_by`, `updated_at`, `updated_by` (omitted from the diagrams).

## Main tables

| Area | Tables |
| --- | --- |
| Users & security | `auth_user`, `accounts_employeeprofile` (role, manager, team, MFA), `accounts_role`, `accounts_capability`, `accounts_loginhistory`, `axes_*` |
| Settings | `core_companyprofile` (single row), `core_numbersequence`, `core_lookupvalue`, `core_taxrate`, `core_systemjobrun` |
| Audit & timeline | `core_auditlog`, `core_activity` |
| Customers | `customers_customer`, `customers_customercontact` |
| Leads | `leads_leadstage`, `leads_lead`, `leads_leadassignment`, `leads_leadstagehistory` |
| Activity | `visits_visit`, `communications_communication`, `tasks_task`, `tasks_taskcomment` |
| Pipeline | `sales_opportunitystage`, `sales_opportunity`, `sales_opportunitystagehistory`, `sales_project` |
| Quotations | `quotations_quotation`, `quotations_quotationrevision`, `quotations_quotationline`, `quotations_approval` |
| Orders | `orders_salesorder`, `orders_salesorderline`, `orders_paymentmilestone` |
| Finance | `invoicing_invoice`, `invoicing_invoiceline`, `invoicing_payment`, `invoicing_paymentallocation` |
| Performance | `performance_kpidefinition`, `performance_salestarget` |
| Documents | `documents_document` |
| Notifications | `notifications_notification`, `notifications_notificationpreference` |
| Import | `reporting_importbatch` |

## Entity-relationship diagrams

Generated from the models (key fields only; GitHub renders these diagrams).

### Users, settings and audit

```mermaid
erDiagram
    Capability }o--o{ Role : "capabilities"
    EmployeeProfile |o--o{ EmployeeProfile : "reporting_manager"
    EmployeeProfile }o--o{ EmployeeProfile : "team_members"
    Role ||--o{ EmployeeProfile : "role"
    User |o--o{ Activity : "user"
    User |o--o{ AuditLog : "user"
    User |o--o{ LoginHistory : "user"
    User ||--o| EmployeeProfile : "user"
    AuditLog {
        DateTime timestamp
        Char action
        Char object_id
        Char object_repr
        JSON changes
        Char message
        GenericIPAddress ip_address
        Char user_agent
    }
    CompanyProfile {
        Char company_name
        Char legal_name
        Char tax_registration_number
        Text address
        Char city
        Char country
        Char phone
        Char email
    }
    NumberSequence {
        Slug code
        Char name
        Char prefix
        Boolean include_year
        Boolean reset_yearly
        Integer padding
        Integer current_year
        Integer last_number
    }
    LookupValue {
        Char category
        Char value
        Integer sort_order
        Boolean is_active
    }
    TaxRate {
        Char name
        Decimal rate
        Boolean is_default
        Boolean is_active
        Integer sort_order
    }
    Activity {
        DateTime timestamp
        Char kind
        Char message
        BigInteger object_id
        Char object_repr
        Boolean financial
    }
    SystemJobRun {
        Char name
        Date last_run_date
        DateTime last_run_at
        Char last_result
    }
    Capability {
        Char code
        Char module
        Char label
    }
    Role {
        Char code
        Char name
        Char description
        Integer max_accounts
        Char data_scope
        Integer sort_order
    }
    EmployeeProfile {
        Char employee_id
        Char department
        Char job_title
        Char phone
        Boolean must_change_password
        Boolean mfa_enabled
        Char mfa_secret
        BigInteger mfa_last_counter
    }
    LoginHistory {
        DateTime timestamp
        Char username
        Char event
        GenericIPAddress ip_address
        Char user_agent
    }
```

### Customers, leads and activity

```mermaid
erDiagram
    Customer |o--o{ Lead : "customer"
    Customer |o--o{ Task : "customer"
    Customer ||--o{ Communication : "customer"
    Customer ||--o{ CustomerContact : "customer"
    Customer ||--o{ Visit : "customer"
    CustomerContact |o--o{ Communication : "contact"
    CustomerContact |o--o{ Visit : "contact"
    Lead |o--o{ Communication : "lead"
    Lead |o--o{ Task : "lead"
    Lead |o--o{ Visit : "lead"
    Lead ||--o{ LeadAssignment : "lead"
    Lead ||--o{ LeadStageHistory : "lead"
    LeadStage |o--o{ LeadStageHistory : "from_stage"
    LeadStage ||--o{ Lead : "stage"
    LeadStage ||--o{ LeadStageHistory : "to_stage"
    Task ||--o{ TaskComment : "task"
    User |o--o{ Customer : "assigned_coordinator"
    User |o--o{ Customer : "assigned_engineer"
    User |o--o{ Lead : "assigned_coordinator"
    User |o--o{ Lead : "assigned_engineer"
    User |o--o{ Lead : "converted_by"
    User |o--o{ LeadAssignment : "assigned_by"
    User |o--o{ LeadAssignment : "coordinator"
    User |o--o{ LeadAssignment : "engineer"
    User |o--o{ LeadStageHistory : "changed_by"
    User |o--o{ Visit : "completed_by"
    User |o--o{ Visit : "next_follow_up_owner"
    User ||--o{ Communication : "employee"
    User ||--o{ Task : "assigned_to"
    User ||--o{ TaskComment : "user"
    User ||--o{ Visit : "assigned_to"
    Visit |o--o{ Task : "visit"
    Customer {
        Char code
        Char company_name
        Char normalized_name
        Char status
        Char contact_person
        Char designation
        Char phone
        Char alt_phone
    }
    CustomerContact {
        Char name
        Char designation
        Char phone
        Char email
        Boolean is_primary
        Char notes
    }
    LeadStage {
        Char name
        Integer order
        Boolean is_won
        Boolean is_lost
        Boolean is_qualified
        Boolean is_active
    }
    Lead {
        Char code
        Char title
        Char company_name
        Char contact_person
        Char designation
        Char email
        Char phone
        Char city
    }
    LeadAssignment {
        DateTime assigned_at
        Char note
    }
    LeadStageHistory {
        DateTime changed_at
        Char note
    }
    Visit {
        Char code
        Char contact_person
        Char site_name
        Date visit_date
        Time start_time
        Time end_time
        Char location
        Text agenda
    }
    Communication {
        Char code
        Char kind
        Char direction
        DateTime occurred_at
        Char subject
        Text summary
        Char outcome
        Char next_action
    }
    Task {
        Char code
        Char title
        Text description
        Char category
        Char priority
        Date start_date
        Date due_date
        Char status
    }
    TaskComment {
        Text text
    }
```

### Pipeline, quotations, orders and finance

```mermaid
erDiagram
    Invoice ||--o{ InvoiceLine : "invoice"
    Invoice ||--o{ PaymentAllocation : "invoice"
    Opportunity |o--o{ Project : "opportunity"
    Opportunity |o--o{ Quotation : "opportunity"
    Opportunity |o--o{ SalesOrder : "opportunity"
    Opportunity ||--o{ OpportunityStageHistory : "opportunity"
    OpportunityStage |o--o{ OpportunityStageHistory : "from_stage"
    OpportunityStage ||--o{ Opportunity : "stage"
    OpportunityStage ||--o{ OpportunityStageHistory : "to_stage"
    Payment ||--o{ PaymentAllocation : "payment"
    Payment ||--o| Payment : "reverses"
    PaymentMilestone |o--o{ Invoice : "milestone"
    Quotation ||--o{ QuotationRevision : "quotation"
    Quotation ||--o{ SalesOrder : "quotation"
    QuotationRevision ||--o{ Approval : "revision"
    QuotationRevision ||--o{ QuotationLine : "revision"
    QuotationRevision ||--o{ SalesOrder : "revision"
    SalesOrder |o--o{ Project : "sales_order"
    SalesOrder ||--o{ Invoice : "order"
    SalesOrder ||--o{ PaymentMilestone : "order"
    SalesOrder ||--o{ SalesOrderLine : "order"
    SalesOrderLine |o--o{ InvoiceLine : "order_line"
    User |o--o{ Approval : "decided_by"
    User |o--o{ Invoice : "cancelled_by"
    User |o--o{ Invoice : "issued_by"
    User |o--o{ Opportunity : "assigned_coordinator"
    User |o--o{ Opportunity : "assigned_engineer"
    User |o--o{ OpportunityStageHistory : "changed_by"
    User |o--o{ Project : "project_manager"
    User |o--o{ QuotationRevision : "decided_by"
    User |o--o{ QuotationRevision : "submitted_by"
    User |o--o{ SalesOrder : "cancelled_by"
    User |o--o{ SalesOrder : "confirmed_by"
    User ||--o{ Quotation : "salesperson"
    User ||--o{ SalesOrder : "assigned_to"
    OpportunityStage {
        Char name
        Integer order
        Integer default_probability
        Boolean is_won
        Boolean is_lost
        Boolean is_active
    }
    Opportunity {
        Char code
        Char title
        Char location
        Decimal estimated_value
        Integer probability
        Date expected_close_date
        Text products_services
        Char competitors
    }
    OpportunityStageHistory {
        Integer probability
        Decimal estimated_value
        DateTime changed_at
        Char note
    }
    Project {
        Char code
        Char name
        Char location
        Char status
        Integer progress
        Date start_date
        Date end_date
        Text description
    }
    Quotation {
        Char number
        Char currency
        Integer current_version
        Char status
        Decimal grand_total
        Date quotation_date
        Date expiry_date
    }
    QuotationRevision {
        Integer version
        Date quotation_date
        Date expiry_date
        Char currency
        Text payment_terms
        Text delivery_terms
        Text scope_of_work
        Text exclusions
    }
    QuotationLine {
        Integer position
        Text description
        Decimal quantity
        Char unit
        Decimal unit_price
        Decimal discount_pct
        Decimal tax_rate_value
        Decimal line_net
    }
    Approval {
        Char decision
        DateTime decided_at
        Text comments
        Decimal grand_total
    }
    SalesOrder {
        Char number
        Date order_date
        Char currency
        Decimal net_amount
        Decimal tax_amount
        Decimal total_amount
        Char status
        Char customer_po_ref
    }
    SalesOrderLine {
        Integer position
        Text description
        Decimal quantity
        Char unit
        Decimal unit_price
        Decimal discount_pct
        Decimal tax_rate_value
        Decimal line_net
    }
    PaymentMilestone {
        Integer sequence
        Char name
        Decimal percentage
        Decimal amount
        Date due_date
    }
    Invoice {
        Char number
        Date invoice_date
        Date due_date
        Char payment_terms
        Char reference
        Char currency
        Decimal subtotal
        Decimal tax_amount
    }
    InvoiceLine {
        Integer position
        Text description
        Decimal quantity
        Char unit
        Decimal unit_price
        Decimal discount_pct
        Decimal tax_rate_value
        Decimal line_net
    }
    Payment {
        Char number
        Date payment_date
        Decimal amount
        Char currency
        Char method
        Char reference
        Char notes
        Boolean is_reversal
    }
    PaymentAllocation {
        Decimal amount
    }
```

### Targets, documents, notifications, imports

```mermaid
erDiagram
    Document ||--o| Document : "previous"
    KPIDefinition ||--o{ SalesTarget : "kpi"
    User |o--o{ SalesTarget : "employee"
    User ||--o{ Document : "uploaded_by"
    User ||--o{ ImportBatch : "uploaded_by"
    User ||--o{ Notification : "user"
    User ||--o{ NotificationPreference : "user"
    KPIDefinition {
        Char code
        Char name
        Char unit
        Char description
        Decimal weight
        Boolean is_active
        Integer sort_order
    }
    SalesTarget {
        Char period_type
        Date period_start
        Decimal target_value
        Char notes
    }
    Document {
        Char title
        Char description
        File file
        Char original_name
        BigInteger size
        Char content_type_mime
        Char sha256
        Integer version
    }
    Notification {
        Char category
        Char title
        Char message
        Char url
        Boolean is_read
        Boolean emailed
        Char dedupe_key
    }
    NotificationPreference {
        Char category
        Boolean in_app
        Boolean email
    }
    ImportBatch {
        Char kind
        Char file_name
        Char status
        JSON headers
        JSON rows
        JSON mapping
        JSON results
        JSON summary
    }
```
