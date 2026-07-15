# GCMicrotechComGraphQLWrapper

Python-only GraphQL wrapper for **microtech büro+ / ERP-complete** using Django, Strawberry GraphQL, a database-backed job queue and a separate Python worker.

The project is currently a prototype for read-only access. Write operations are intentionally not implemented yet.

## Goal

This project provides a safe and extensible API layer in front of microtech.

The important rule is:

> GraphQL never talks directly to COM.
> Only the worker is allowed to communicate with microtech.

This keeps the API request lifecycle independent from Windows COM and makes the system easier to debug, queue, retry and secure.

## Architecture

```text
Django + Strawberry GraphQL
        ↓
MicrotechJob table / queue
        ↓
Python worker
        ↓
MicrotechClient
        ↓
Windows only: pywin32 / BpNT.Application / COM
        ↓
microtech büro+ / ERP-complete
```

## Current status

Implemented and tested:

- Django project
- Strawberry GraphQL endpoint
- MicrotechJob model as queue table
- Safe job claiming in the worker
- Linux/macOS dummy microtech client
- Windows COM microtech client
- `.env` loading through `django-environ`
- Optional Windows dependency `pywin32`
- `microtechVersion`
- `requestCustomer(customerNumber)` with dummy data on non-Windows systems
- `microtechJob(jobId)` for polling job state and result

Successfully tested end-to-end on Windows:

```text
Linux client
→ GraphQL on Windows Server
→ Django
→ MicrotechJob queue
→ Windows worker
→ pywin32
→ BpNT.Application
→ microtech GetVersion()
→ result returned through GraphQL
```

Confirmed real microtech COM result:

```json
{
  "version": "26.0.7145",
  "source": "microtech-com"
}
```

## Requirements

### General

- Python 3.12
- uv
- Git

The project is pinned to Python 3.12:

```toml
requires-python = ">=3.12,<3.13"
```

### Windows only

For real microtech COM access:

- Windows Server / Windows client
- microtech büro+ / ERP-complete installed
- COM access enabled in microtech
- A microtech user with COM access permission
- `pywin32`

The Windows dependency is optional:

```toml
[project.optional-dependencies]
windows = [
    "pywin32>=311; sys_platform == 'win32'",
]
```

## Project structure

```text
GCMicrotechComGraphQLWrapper/
├── api/
│   ├── manage.py
│   ├── config/
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── asgi.py
│   │   └── wsgi.py
│   └── apps/
│       └── microtech_jobs/
│           ├── admin.py
│           ├── apps.py
│           ├── models.py
│           ├── schema.py
│           └── migrations/
├── worker/
│   ├── microtech_worker.py
│   └── microtech_client.py
├── docs/
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── .gitignore
└── README.md
```

## Environment variables

Copy the example file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
copy .env.example .env
notepad .env
```

Example:

```env
# Django
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

# microtech COM
MICROTECH_FIRMA=
MICROTECH_MANDANT=
MICROTECH_BENUTZER=
MICROTECH_PASSWORT=
```

For network testing from another machine, include the Windows server IP:

```env
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,10.0.0.5
```

Do not commit `.env`.

## Installation

### Linux/macOS development setup

```bash
git clone git@github.com:Get-Company/GCMicrotechComGraphQLWrapper.git
cd GCMicrotechComGraphQLWrapper

cp .env.example .env
# edit .env with your values
bash entrypoint.sh
```

`entrypoint.sh` runs: `uv sync --frozen`, import checks, `migrate`, `check`, and optionally a restart hook via `DEPLOY_RESTART_COMMAND`.

Run Django:

```bash
uv run python api/manage.py runserver
```

If port 8000 is unavailable:

```bash
uv run python api/manage.py runserver 8888
```

Run the worker:

```bash
uv run python worker/microtech_worker.py
```

On Linux/macOS the project automatically uses `DummyMicrotechClient`.

### Windows setup with COM support

```powershell
git clone git@github.com:Get-Company/GCMicrotechComGraphQLWrapper.git
cd GCMicrotechComGraphQLWrapper

copy .env.example .env
notepad .env
.\entrypoint.ps1
```

`entrypoint.ps1` runs: `uv sync --frozen --extra windows`, pywin32/strawberry import checks, `migrate`, `check`, and optionally a restart hook via `$env:DEPLOY_RESTART_COMMAND`.

Run Django on localhost:

```powershell
uv run python api/manage.py runserver 127.0.0.1:8888
```

Run Django for access from another machine in the network:

```powershell
uv run python api/manage.py runserver 0.0.0.0:8888
```

Run the worker:

```powershell
uv run python worker/microtech_worker.py
```

## GraphQL endpoint

Default local endpoint:

```text
http://127.0.0.1:8000/graphql/
```

Windows test endpoint used during development:

```text
http://10.0.0.5:8888/graphql/
```

## Agent API reference

This section is the authoritative reference for agents and integrations. It covers every available query and mutation with full field lists and curl examples.

### General usage pattern

All write operations follow a two-step async pattern:

1. Send a mutation → receive a `jobId`
2. Poll with the matching job query until `status` is `DONE` or `FAILED`

Job status values: `QUEUED` → `RUNNING` → `DONE` | `FAILED`

All mutations return `JobAcceptedType`:

```graphql
{
  accepted: Boolean!
  jobId: ID
  status: String!
  message: String!
  retryAfterSeconds: Int!
}
```

Start polling after `retryAfterSeconds` (always `2`).

---

### Queries

#### health

```graphql
query {
  health
}
```

Returns `"ok"`. Use as a liveness check.

```bash
curl -s http://127.0.0.1:8000/graphql/ \
  -H "Content-Type: application/json" \
  -d '{"query":"query { health }"}'
```

---

#### microtechJob — generic job poll

Returns raw `result_data` as JSON. Use `productJob`, `customerJob`, or `vorgangJob` for typed results.

```graphql
query {
  microtechJob(jobId: "<uuid>") {
    jobId
    status
    message
    result
    errorMessage
  }
}
```

```bash
curl -s http://127.0.0.1:8000/graphql/ \
  -H "Content-Type: application/json" \
  -d '{"query":"query { microtechJob(jobId: \"<uuid>\") { jobId status message result errorMessage } }"}'
```

---

#### productJob — typed product result

Use after `requestProduct` or `updateProduct`.

```graphql
query {
  productJob(jobId: "<uuid>") {
    jobId
    status
    message
    deleted
    errorMessage
    product {
      erpNumber
      name
      description
      descriptionShort
      isActive
      factor
      unit
      minPurchase
      purchaseUnit
      sortOrder
      taxKey
      taxRate
      customsTariffNumber
      weightGrossKg
      weightNetKg
      price
      rebateQuantity
      rebatePrice
      specialPrice
      specialStartDate
      specialEndDate
      warehouseNumber
      stock
      storageLocation
      deleted
      images
      source
    }
  }
}
```

---

#### customerJob — typed customer result

Use after any customer or address mutation.

```graphql
query {
  customerJob(jobId: "<uuid>") {
    jobId
    status
    message
    deleted
    errorMessage
    customer {
      customerNumber
      erpAddressNumber
      salutation
      firstName
      lastName
      name1
      name2
      name3
      street
      zipCode
      city
      email
      phone
      department
      country
      defaultShippingAddressNumber
      defaultBillingAddressNumber
      source
      addresses {
        addressNumber
        addressSubNumber
        isDefaultShipping
        isDefaultBilling
        name1
        name2
        name3
        street
        zipCode
        city
        email
        phone
        department
        country
        contacts {
          addressNumber
          addressSubNumber
          contactNumber
          isDefault
          salutation
          firstName
          lastName
          displayName
          department
          email
          phone
        }
      }
    }
    postalAddress {
      addressNumber
      addressSubNumber
      isDefaultShipping
      isDefaultBilling
      name1
      street
      zipCode
      city
      email
      phone
      country
      contacts { contactNumber firstName lastName email phone }
    }
    contactPerson {
      addressNumber
      addressSubNumber
      contactNumber
      isDefault
      salutation
      firstName
      lastName
      displayName
      department
      email
      phone
    }
  }
}
```

---

#### vorgangJob — typed Vorgang result

Use after `requestVorgang`, `createVorgang`, or `updateVorgang`.

```graphql
query {
  vorgangJob(jobId: "<uuid>") {
    jobId
    status
    message
    errorMessage
    vorgang {
      belegNr
      vorgangArt
      erpAddressNumber
      orderNumber
      date
      description
      netto
      brutto
      currency
      status
      source
      customer { customerNumber name1 city email }
      positions {
        belegNr
        positionNr
        erpNumber
        name
        quantity
        unit
        unitPrice
        totalPrice
        taxKey
        discountRate
        product { erpNumber name price stock }
      }
    }
  }
}
```

---

### Mutations

#### ping

```graphql
mutation { ping }
```

Returns `"pong"`. Use to verify the mutation endpoint is reachable.

---

#### microtechVersion

Queues a job to fetch the microtech ERP version via COM.

```graphql
mutation {
  microtechVersion {
    accepted jobId status message retryAfterSeconds
  }
}
```

```bash
curl -s http://127.0.0.1:8000/graphql/ \
  -H "Content-Type: application/json" \
  -d '{"query":"mutation { microtechVersion { accepted jobId status message retryAfterSeconds } }"}'
```

Poll with `microtechJob`. Result shape: `{ "version": "26.0.7145", "source": "microtech-com" }`

---

### Customer mutations

#### requestCustomer

Fetch a customer by customer number.

```graphql
mutation {
  requestCustomer(customerNumber: "10005") {
    accepted jobId status message retryAfterSeconds
  }
}
```

Poll with `customerJob`. Result: full `CustomerType` with addresses and contacts.

---

#### createCustomer

```graphql
mutation {
  createCustomer(
    customerNumber: "10005"
    input: {
      salutation: "Herr"
      firstName: "Max"
      lastName: "Mustermann"
      name1: "Mustermann GmbH"
      street: "Musterstraße 1"
      zipCode: "12345"
      city: "Musterstadt"
      email: "max@example.com"
      phone: "+49 123 456789"
      country: "Deutschland"
    }
  ) {
    accepted jobId status message retryAfterSeconds
  }
}
```

All `CustomerInput` fields are optional: `salutation`, `firstName`, `lastName`, `name1`, `name2`, `name3`, `street`, `zipCode`, `city`, `email`, `phone`, `department`, `country`, `defaultShippingAddressNumber`, `defaultBillingAddressNumber`.

Poll with `customerJob`.

---

#### updateCustomer

```graphql
mutation {
  updateCustomer(
    customerNumber: "10005"
    input: { email: "neuemail@example.com" city: "Berlin" }
  ) {
    accepted jobId status message retryAfterSeconds
  }
}
```

Same `CustomerInput` as `createCustomer`. At least one field must be set.

---

#### deleteCustomer

```graphql
mutation {
  deleteCustomer(customerNumber: "10005") {
    accepted jobId status message retryAfterSeconds
  }
}
```

---

### Postal address mutations

Addresses are identified by `addressNumber` (= `erpAddressNumber` of the customer) and `addressSubNumber`.

#### createPostalAddress

```graphql
mutation {
  createPostalAddress(
    addressNumber: 1234
    input: {
      isDefaultShipping: true
      isDefaultBilling: false
      name1: "Lieferadresse GmbH"
      street: "Lieferweg 5"
      zipCode: "80331"
      city: "München"
      country: "Deutschland"
    }
  ) {
    accepted jobId status message retryAfterSeconds
  }
}
```

`PostalAddressInput` fields (all optional): `isDefaultShipping`, `isDefaultBilling`, `name1`, `name2`, `name3`, `street`, `zipCode`, `city`, `email`, `phone`, `department`, `country`.

---

#### updatePostalAddress

```graphql
mutation {
  updatePostalAddress(
    addressNumber: 1234
    addressSubNumber: 1
    input: { city: "Hamburg" }
  ) {
    accepted jobId status message retryAfterSeconds
  }
}
```

---

#### deletePostalAddress

```graphql
mutation {
  deletePostalAddress(addressNumber: 1234 addressSubNumber: 1) {
    accepted jobId status message retryAfterSeconds
  }
}
```

---

### Contact person mutations

Contacts belong to an address (`addressNumber` + `addressSubNumber`).

#### createContactPerson

```graphql
mutation {
  createContactPerson(
    addressNumber: 1234
    addressSubNumber: 1
    input: {
      salutation: "Frau"
      firstName: "Anna"
      lastName: "Beispiel"
      email: "anna@example.com"
      isDefault: true
    }
  ) {
    accepted jobId status message retryAfterSeconds
  }
}
```

`ContactPersonInput` fields (all optional): `isDefault`, `salutation`, `firstName`, `lastName`, `displayName`, `department`, `email`, `phone`.

---

#### updateContactPerson

```graphql
mutation {
  updateContactPerson(
    addressNumber: 1234
    addressSubNumber: 1
    contactNumber: 1
    input: { phone: "+49 89 123456" }
  ) {
    accepted jobId status message retryAfterSeconds
  }
}
```

---

#### deleteContactPerson

```graphql
mutation {
  deleteContactPerson(
    addressNumber: 1234
    addressSubNumber: 1
    contactNumber: 1
  ) {
    accepted jobId status message retryAfterSeconds
  }
}
```

---

### Vorgang mutations

A Vorgang is a document (order, invoice, etc.) identified by `belegNr`. `vorgangArt` is the microtech document type code (e.g. `10` = Angebot, `20` = Auftrag).

#### requestVorgang

```graphql
mutation {
  requestVorgang(belegNr: "A2024-00001") {
    accepted jobId status message retryAfterSeconds
  }
}
```

Poll with `vorgangJob`.

---

#### createVorgang

```graphql
mutation {
  createVorgang(input: {
    vorgangArt: 20
    customerNumber: "10005"
    orderNumber: "ORD-2024-001"
    description: "Testauftrag"
    date: "2024-01-15"
    currency: "EUR"
    positions: [
      { erpNumber: "ART-001" quantity: "2" unit: "Stk" price: "49.90" }
      { erpNumber: "ART-002" quantity: "1" }
    ]
  }) {
    accepted jobId status message retryAfterSeconds
  }
}
```

`CreateVorgangInput`: `vorgangArt` (Int, required), `customerNumber` (String, required), `orderNumber`, `description`, `date` (ISO 8601), `currency`, `positions` (list of `VorgangPositionInput`).

`VorgangPositionInput`: `erpNumber` (required), `quantity` (required), `unit` (optional), `price` (optional, net unit price).

---

#### updateVorgang

```graphql
mutation {
  updateVorgang(
    belegNr: "A2024-00001"
    input: {
      description: "Geänderter Auftrag"
      positions: [
        { erpNumber: "ART-001" quantity: "3" }
      ]
    }
  ) {
    accepted jobId status message retryAfterSeconds
  }
}
```

`UpdateVorgangInput`: `orderNumber`, `description`, `date`, `currency`, `positions`. Pass `positions: []` to delete all positions; omit `positions` to leave them unchanged.

---

### Product mutations

#### requestProduct

```graphql
mutation {
  requestProduct(erpNumber: "ART-001") {
    accepted jobId status message retryAfterSeconds
  }
}
```

Poll with `productJob`.

---

#### updateProduct

```graphql
mutation {
  updateProduct(
    erpNumber: "ART-001"
    input: {
      priceTrees: [{ tree: "Vk0", price: "59.90" }]
      isActive: true
      description: "Neue Beschreibung"
    }
  ) {
    accepted jobId status message retryAfterSeconds
  }
}
```

`UpdateProductInput` fields (all optional): `name`, `description`, `descriptionShort`, `isActive`, `factor`, `unit`, `minPurchase`, `purchaseUnit`, `sortOrder`, `taxKey`, `price`, `rebateQuantity`, `rebatePrice`, `specialPrice`, `specialStartDate`, `specialEndDate`, `priceTrees`. At least one field must be set.

Use `priceTrees` to write explicit Microtech sales price trees. Valid `tree` values are `Vk0` through `Vk99`. Each entry may contain `price`, `rebateQuantity`, `rebatePrice`, `specialPrice`, `specialStartDate`, and `specialEndDate`. The legacy top-level price fields write only to `Vk0`.

Project rule: product price writes must use `priceTrees` with `Vk0`. The Graph API mirrors `Vk0` to `Vk1`; product reads use the default `Vk0` fields returned by `ProductType`.

---

### Complete two-step example

Step 1 — enqueue job:

```bash
curl -s http://127.0.0.1:8000/graphql/ \
  -H "Content-Type: application/json" \
  -d '{"query":"mutation { requestCustomer(customerNumber: \"10005\") { accepted jobId retryAfterSeconds } }"}'
```

Response:

```json
{
  "data": {
    "requestCustomer": {
      "accepted": true,
      "jobId": "d07981a2-4d76-47c5-9c16-816ef4b63b23",
      "retryAfterSeconds": 2
    }
  }
}
```

Step 2 — poll after `retryAfterSeconds`:

```bash
curl -s http://127.0.0.1:8000/graphql/ \
  -H "Content-Type: application/json" \
  -d '{"query":"query { customerJob(jobId: \"d07981a2-4d76-47c5-9c16-816ef4b63b23\") { status errorMessage customer { customerNumber name1 city email } } }"}'
```

Repeat until `status` is `DONE` or `FAILED`.

## Worker behavior

The worker claims queued jobs safely.

The claiming logic ensures that only one worker processes a job:

1. Find the oldest `QUEUED` job.
2. Update that exact job to `RUNNING` only if it is still `QUEUED`.
3. Process the job only if the update affected exactly one row.

This protects against duplicate processing when multiple workers are running.

## Microtech clients

### DummyMicrotechClient

Used automatically on Linux/macOS.

Version response:

```json
{
  "version": "DUMMY-LINUX-NO-COM",
  "source": "microtech-client-dummy"
}
```

Customer response:

```json
{
  "customerNumber": "10005",
  "name": "DUMMY Kunde GmbH",
  "city": "Ruhpolding",
  "source": "microtech-client-dummy"
}
```

### WindowsComMicrotechClient

Used automatically on Windows.

COM ProgID:

```text
BpNT.Application
```

COM initialization:

```python
self.bp.Init(
    self.connection_name,
    "",
    self.username,
    self.password,
)
self.bp.SelectMand(self.mandant)
```

The second argument is intentionally an empty connection key.

`get_version()` uses:

```python
self.bp.GetVersion()
```

`get_customer()` is intentionally not implemented yet on Windows.

## microtech COM notes

Important points from the COM documentation:

- ProgID is `BpNT.Application`
- `Init(...)` must be called first
- `SelectMand(...)` must be called after `Init(...)`
- `GetVersion()` returns the microtech version
- `DataSetInfos` can be used to inspect available datasets
- Address data is expected around `DataSetInfos["Adressen"]`, but field names must be inspected before implementation

microtech requirements:

- COM access must be enabled for the client/mandant
- COM access must be enabled for the user
- microtech should have been started normally after updates
- no modal update/license/maintenance windows should block COM

## Known development issues and fixes

### CSRF error on GraphQL POST

Error:

```text
CSRF verification failed. Request aborted.
CSRF cookie not set.
```

Fix:

The GraphQL endpoint is wrapped with `csrf_exempt`.

This is acceptable for the prototype, but production needs authentication.

### Missing SQLite table

Error:

```text
sqlite3.OperationalError: no such table: microtech_jobs_microtechjob
```

Fix:

```bash
uv run python api/manage.py migrate
```

### Readonly SQLite database on Windows

Error:

```text
sqlite3.OperationalError: attempt to write a readonly database
```

Cause:

The database file or `api` directory is not writable by the Windows user running Django.

Fix in elevated PowerShell:

```powershell
cd D:\GCMicrotechComGraphQLWrapper
icacls api\db.sqlite3 /grant "classei\administrator:F"
icacls api /grant "classei\administrator:F"
```

Then restart Django and the worker.

### Port 8000 not accessible on Windows

Error:

```text
Error: You don't have permission to access that port.
```

Workaround:

Use another port:

```powershell
uv run python api/manage.py runserver 0.0.0.0:8888
```

## Security notes

This project is currently a prototype.

Before production use:

- Add API authentication
- Replace SQLite with PostgreSQL
- Do not use Django `runserver`
- Run the worker as a managed service
- Store secrets securely
- Limit network access to the GraphQL endpoint
- Add logging and monitoring
- Add rate limiting
- Add permission checks per operation
- Keep COM access isolated in the worker

## Next steps

The next implementation step should be:

> Inspect microtech dataset metadata for `Adressen` before implementing real customer lookup.

Do not guess field names.

Suggested next command on Windows:

```powershell
Select-String -Path worker\microtech_client.py -Pattern "def get_customer|DataSetInfos|CreateDataSet|GetVersion"
```

Then add a temporary/internal method to inspect:

```text
DataSetInfos["Adressen"]
```

Only after the available dataset and field names are known should Windows `get_customer(customer_number)` be implemented.
