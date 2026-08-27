# MCP for GC-Bridge and Microtech GraphQL

The Docker stack starts two separate Streamable-HTTP MCP endpoints on the GC-Bridge host (`10.0.0.165`). Both are authenticated with the same bearer token, but expose deliberately different tool sets:

| Endpoint | Purpose |
| --- | --- |
| `http://10.0.0.165:8001/bridge/mcp` | Local GraphQL-job queue, Celery and order-workflow diagnostics/recovery |
| `http://10.0.0.165:8001/graphql/mcp` | Microtech GraphQL status and single customer/product/order lookups |

The GraphQL wrapper used by the MCP is `http://10.0.0.5:4711/graphql/`.

## Deployment

On the GC-Bridge server, add the following to the local `.env`. Generate the token there; never commit it.

```env
MICROTECH_GRAPHQL_URL=http://10.0.0.5:4711/graphql/
MCP_PORT=8001
MCP_OPERATIONS_TOKEN=<a-random-64-character-token>
MCP_ALLOWED_HOSTS=10.0.0.165,10.0.0.165:*
```

For example, generate the token on the server with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then deploy the updated stack:

```bash
docker compose up -d --build
```

The MCP client must send `Authorization: Bearer <MCP_OPERATIONS_TOKEN>` for every request. Restrict port `8001` in the firewall to the trusted internal clients. Because bearer tokens and customer data travel over this connection, put the endpoint behind TLS/mTLS before it crosses a network segment that is not trusted.

## Operations procedure

Start with `get_bridge_diagnosis`. It returns local job status counts, stale jobs, failed order workflows, active Celery workers, GraphQL worker state and suggested next steps.

All mutation-capable tools require an exact confirmation argument. This prevents a natural-language request from accidentally starting, resuming, cancelling or restarting work.

| Tool | Confirmation | Effect |
| --- | --- | --- |
| `poll_job_now` | `POLL` | Performs one immediate remote status poll; a successful job may run its existing continuation. |
| `reconcile_order_workflows` | `ABGLEICH` | Marks failed or orphaned order workflows consistently. |
| `resume_order_workflow` | `FORTSETZEN` | Re-submits the current failed workflow step. Verify remote failure first. |
| `abort_order_workflow` | `WORKFLOW ABBRECHEN` | Cancels the workflow locally only; it does not cancel remote work. |
| `restart_order_workflow` | `NEUSTARTEN` | Cancels locally and starts the chain again. Only use after the old remote job is confirmed unavailable. |
| `cancel_microtech_job` | `JOB ABBRECHEN` | Cancels the remote job and removes its local record. |
| `start_microtech_worker` | `WORKER STARTEN` | Enqueues the existing audited Celery maintenance operation. |

`fetch_customer`, `fetch_product` and `fetch_order` do not change business data. Their GraphQL API nevertheless uses temporary asynchronous read jobs, so the tools are intentionally not marked read-only at the protocol layer.
