2026-08-17 09:47:23.349 | ERROR    | orders.management.commands.shopware_sync_open_orders:handle:54 | Shopware open-order sync failed.
Traceback (most recent call last):
File "/app/orders/management/commands/shopware_sync_open_orders.py", line 49, in handle
summary = OrderSyncService().sync_open_orders(
File "/app/orders/services/order_sync.py", line 101, in sync_open_orders
response = service.list_all_open_by_sales_channel(sales_channel_id=sales_channel_id)
File "/app/shopware/services/order.py", line 101, in list_all_open_by_sales_channel
response = self.list_open_by_sales_channel(
File "/app/shopware/services/order.py", line 88, in list_open_by_sales_channel
return self.request_post(self.search_path, payload=payload)
File "/app/shopware/services/shopware6.py", line 123, in request_post
result = self._request_with_retry(
File "/app/shopware/services/shopware6.py", line 37, in _request_with_retry
return request_method(*args, **kwargs)
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 221, in request_post
response_dict = self._make_request(
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 515, in _make_request
self._get_session()
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 881, in _get_session
self._get_token()
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 700, in _get_token
token = self._get_access_token_by_resource_owner()
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 774, in _get_access_token_by_resource_owner
self.token = client.fetch_token(
File "/app/.venv/lib/python3.12/site-packages/authlib/oauth2/client.py", line 246, in fetch_token
return self._fetch_token(
File "/app/.venv/lib/python3.12/site-packages/authlib/oauth2/client.py", line 445, in _fetch_token
return self.parse_response_token(resp)
File "/app/.venv/lib/python3.12/site-packages/authlib/oauth2/client.py", line 418, in parse_response_token
token = resp.json()
File "/app/.venv/lib/python3.12/site-packages/httpx/_models.py", line 832, in json
return jsonlib.loads(self.content, **kwargs)
File "/usr/local/lib/python3.12/json/__init__.py", line 346, in loads
return _default_decoder.decode(s)
File "/usr/local/lib/python3.12/json/decoder.py", line 338, in decode
obj, end = self.raw_decode(s, idx=_w(s, 0).end())
File "/usr/local/lib/python3.12/json/decoder.py", line 356, in raw_decode
raise JSONDecodeError("Expecting value", s, err.value) from None
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
2026-08-17 09:52:24.447 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 09:52:24.874 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 09:52:25.228 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 09:52:25.229 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 0,
"customers_upserted": 0,
"details_upserted": 0,
"orders_created": 0,
"orders_failed": 0,
"orders_promoted": 0,
"orders_seen": 0,
"orders_updated": 0
}
2026-08-17 09:57:24.414 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 09:57:24.808 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 09:57:25.227 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 09:57:25.228 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 0,
"customers_upserted": 0,
"details_upserted": 0,
"orders_created": 0,
"orders_failed": 0,
"orders_promoted": 0,
"orders_seen": 0,
"orders_updated": 0
}
2026-08-17 10:02:24.521 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:02:24.904 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:02:25.307 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:02:25.308 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 0,
"customers_upserted": 0,
"details_upserted": 0,
"orders_created": 0,
"orders_failed": 0,
"orders_promoted": 0,
"orders_seen": 0,
"orders_updated": 0
}
2026-08-17 10:07:24.684 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:07:25.050 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:07:25.441 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:07:25.442 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 0,
"customers_upserted": 0,
"details_upserted": 0,
"orders_created": 0,
"orders_failed": 0,
"orders_promoted": 0,
"orders_seen": 0,
"orders_updated": 0
}
2026-08-17 10:12:24.861 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:12:25.243 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:12:25.607 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:12:25.608 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 0,
"customers_upserted": 0,
"details_upserted": 0,
"orders_created": 0,
"orders_failed": 0,
"orders_promoted": 0,
"orders_seen": 0,
"orders_updated": 0
}
2026-08-17 10:17:25.111 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:17:25.476 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:17:25.872 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:17:25.873 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 0,
"customers_upserted": 0,
"details_upserted": 0,
"orders_created": 0,
"orders_failed": 0,
"orders_promoted": 0,
"orders_seen": 0,
"orders_updated": 0
}
2026-08-17 10:22:25.369 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:22:25.724 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:22:26.072 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:22:26.073 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 0,
"customers_upserted": 0,
"details_upserted": 0,
"orders_created": 0,
"orders_failed": 0,
"orders_promoted": 0,
"orders_seen": 0,
"orders_updated": 0
}
2026-08-17 10:27:25.434 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 1 offene Bestellung(en) fuer Upsert.
2026-08-17 10:27:27.128 | INFO     | orders.services.order_sync:promote_new_order_to_in_progress:229 | Bestellung 10044 nach dem Anlegen auf 'in_progress' gesetzt.
2026-08-17 10:27:27.500 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:27:27.897 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:27:27.898 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 2,
"customers_upserted": 1,
"details_upserted": 1,
"orders_created": 1,
"orders_failed": 0,
"orders_promoted": 1,
"orders_seen": 1,
"orders_updated": 0
}
2026-08-17 10:32:25.769 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 1 offene Bestellung(en) fuer Upsert.
2026-08-17 10:32:27.144 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:32:27.515 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:32:27.517 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 2,
"customers_upserted": 1,
"details_upserted": 1,
"orders_created": 0,
"orders_failed": 0,
"orders_promoted": 0,
"orders_seen": 1,
"orders_updated": 1
}
2026-08-17 10:36:25.491 | INFO     | logging:callHandlers:1762 | Order-Sync-Workflow #18 für Bestellung 68 (erp_nr=10026) gestartet.
2026-08-17 10:36:47.023 | INFO     | orders.services.order_rule_resolver:resolve_for_order:142 | Order 10044: evaluating 3 active rule(s).
2026-08-17 10:36:47.023 | INFO     | orders.services.order_rule_resolver:_matches_rule:225 | Order 10044: rule 9 ('T5 für CH') condition 10 -> field='billing_address__country_code' operator='equal' expected='CH' actual='DE' => NO_MATCH
2026-08-17 10:36:47.024 | INFO     | orders.services.order_rule_resolver:_matches_rule:243 | Order 10044: rule 9 ('T5 für CH') final condition result=False (logic='all').
2026-08-17 10:36:47.024 | INFO     | orders.services.order_rule_resolver:resolve_for_order:152 | Order 10044: rule 9 ('T5 für CH') did not match.
2026-08-17 10:36:47.024 | INFO     | orders.services.order_rule_resolver:_matches_rule:225 | Order 10044: rule 6 ('P für Paypal') condition 6 -> field='payment_method' operator='contains' expected='paypal' actual='PayPal' => MATCH
2026-08-17 10:36:47.024 | INFO     | orders.services.order_rule_resolver:_matches_rule:243 | Order 10044: rule 6 ('P für Paypal') final condition result=True (logic='all').
2026-08-17 10:36:47.025 | INFO     | orders.services.order_rule_resolver:resolve_for_order:165 | Order 10044: rule 6 ('P für Paypal') matched with 1 dataset action(s).
2026-08-17 10:37:25.908 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 07a1e910ba9a40269c2f70d16066f167: 1 offene Bestellung(en) fuer Upsert.
2026-08-17 10:37:27.412 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 75149aa1e5dd4720a0982c01533c53d4: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:37:27.802 | INFO     | orders.services.order_sync:sync_open_orders:103 | SalesChannel 4aa8b458c39e4cf399d63310f5d79c1a: 0 offene Bestellung(en) fuer Upsert.
2026-08-17 10:37:27.804 | INFO     | orders.management.commands.shopware_sync_open_orders:handle:58 | {
"addresses_upserted": 2,
"customers_upserted": 1,
"details_upserted": 1,
"orders_created": 0,
"orders_failed": 0,
"orders_promoted": 0,
"orders_seen": 1,
"orders_updated": 1
}