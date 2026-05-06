# Graph Report - GC-Bridge-4  (2026-05-06)

## Corpus Check
- 370 files · ~564,402 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4846 nodes · 15762 edges · 91 communities detected
- Extraction: 63% EXTRACTED · 37% INFERRED · 0% AMBIGUOUS · INFERRED: 5814 edges (avg confidence: 0.67)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 92|Community 92]]
- [[_COMMUNITY_Community 93|Community 93]]
- [[_COMMUNITY_Community 94|Community 94]]
- [[_COMMUNITY_Community 95|Community 95]]
- [[_COMMUNITY_Community 96|Community 96]]
- [[_COMMUNITY_Community 97|Community 97]]
- [[_COMMUNITY_Community 98|Community 98]]
- [[_COMMUNITY_Community 99|Community 99]]

## God Nodes (most connected - your core abstractions)
1. `get()` - 279 edges
2. `filter()` - 245 edges
3. `create()` - 115 edges
4. `Product` - 105 edges
5. `BaseAdmin` - 94 edges
6. `ShopwareSettings` - 85 edges
7. `gi` - 85 edges
8. `PriceIncreaseAdmin` - 83 edges
9. `kn` - 76 edges
10. `Price` - 75 edges

## Surprising Connections (you probably didn't know these)
- `scrollSidebarNav()` --calls--> `get()`  [INFERRED]
  staticfiles/unfold/js/app.js → mappei/services/scheduler.py
- `affectedCheckboxes()` --calls--> `filter()`  [INFERRED]
  staticfiles/admin/js/actions.js → core/tests.py
- `winnow()` --calls--> `filter()`  [INFERRED]
  staticfiles/admin/js/vendor/jquery/jquery.js → core/tests.py
- `Placeholder()` --calls--> `get()`  [INFERRED]
  staticfiles/admin/js/vendor/select2/select2.full.js → mappei/services/scheduler.py
- `ArrayAdapter()` --calls--> `get()`  [INFERRED]
  staticfiles/admin/js/vendor/select2/select2.full.js → mappei/services/scheduler.py

## Hyperedges (group relationships)
- **Order three-part status display (order, payment, shipping) rendered together in state section** — order_expand_section_order_state, order_expand_section_payment_state, order_expand_section_shipping_state [EXTRACTED 1.00]
- **Template exposes transitions_meta_url as data attribute consumed by swRefreshTransitions JS to dynamically update order state buttons** — order_expand_section_template, order_expand_section_transitions_meta_url, order_expand_section_sw_refresh_transitions [INFERRED 0.85]

## Communities

### Community 0 - "Community 0"
Cohesion: 0.01
Nodes (337): ABC, _get_product_prompt_queryset(), get_rewriteable_product_field_choices(), get_rewriteable_product_field_names(), get_rewriteable_product_fields(), set(), Title(), _map_field_name() (+329 more)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (262): $(), A(), Aa(), add(), addBox(), addControllers(), addElements(), addPlugins() (+254 more)

### Community 2 - "Community 2"
Cohesion: 0.01
Nodes (125): p(), ci(), un(), Ct(), p(), Ze(), c(), StopPropagation() (+117 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (225): AIProviderConfigAdmin, AIRewriteJobAdmin, AIRewriteJobRequestForm, AIRewriteJobRequestView, AIRewritePromptAdmin, apply_rewrite_detail(), approve_and_apply_selected(), approve_selected() (+217 more)

### Community 4 - "Community 4"
Cohesion: 0.01
Nodes (246): activateButtonLoader(), createLoaderElement(), getInsertionReference(), insertLoaderElement(), shouldHandleLink(), shouldHandleSubmitter(), buildResult(), initialize() (+238 more)

### Community 5 - "Community 5"
Cohesion: 0.02
Nodes (170): test_product_field_action_creates_job_when_single_prompt(), BaseService, Command, lookup_with_erp(), Command, Command, _resolve_product_tax(), _sync_expired_specials_to_microtech() (+162 more)

### Community 6 - "Community 6"
Cohesion: 0.02
Nodes (29): on(), Wt(), lt(), fcssescape(), inspectPrefiltersOrTransports(), at(), ArrowLeft(), ArrowRight() (+21 more)

### Community 7 - "Community 7"
Cohesion: 0.02
Nodes (100): Command, Command, Command, access_service(), approve_selected(), approved_vacation_days_display(), bridge_days_display(), cancel_selected() (+92 more)

### Community 8 - "Community 8"
Cohesion: 0.05
Nodes (170): dismissDeleteRelatedObjectPopup(), A(), ae(), an(), at(), B(), be(), bn() (+162 more)

### Community 9 - "Community 9"
Cohesion: 0.04
Nodes (123): _(), a(), Ae(), ar(), B(), bi(), Bn(), br() (+115 more)

### Community 10 - "Community 10"
Cohesion: 0.03
Nodes (25): bindDragEvents(), categoryById(), icon(), isHiddenByCollapse(), loadProducts(), moveCategory(), postForm(), readCollapsed() (+17 more)

### Community 11 - "Community 11"
Cohesion: 0.05
Nodes (70): BaseAutocompleteView, BaseStackedInline, Command, ActionInline, ConditionInline, Media, MicrotechDatasetCatalogAdmin, MicrotechDatasetFieldAdmin (+62 more)

### Community 12 - "Community 12"
Cohesion: 0.1
Nodes (52): $(), A(), At(), b(), C(), ct(), Dt(), E() (+44 more)

### Community 13 - "Community 13"
Cohesion: 0.08
Nodes (43): an(), b(), ce(), ct(), De(), dt(), e(), en() (+35 more)

### Community 14 - "Community 14"
Cohesion: 0.08
Nodes (32): Tt(), a(), at(), C(), d(), dt(), e(), f() (+24 more)

### Community 15 - "Community 15"
Cohesion: 0.07
Nodes (16): AiConfig, AppConfig, CoreConfig, CustomerConfig, HrConfig, completed(), _is_server_process(), MappeiConfig (+8 more)

### Community 16 - "Community 16"
Cohesion: 0.31
Nodes (19): appendOption(), bindControl(), clearOptions(), clearProgressMessages(), ensureStyles(), fetchAndCacheTransitions(), getActionsForControl(), getCsrfToken() (+11 more)

### Community 17 - "Community 17"
Cohesion: 0.16
Nodes (6): BridgeOrderEntity, Query the database to get all orders with payment_state, shipping_state, and ord, This export needs to be called, The entity is produced by ERP. Simply use the same names         self.hans = ent, Returns a list of dictionaries containing product information (id, quantity, uni, Query()

### Community 18 - "Community 18"
Cohesion: 0.38
Nodes (8): dashboard_callback(), _detect_price_column(), _fetch_discounted_rows(), _fetch_open_order_rows(), _filter_dashboard_apps(), _format_datetime(), _format_discount_percent(), _format_eur()

### Community 19 - "Community 19"
Cohesion: 0.22
Nodes (1): Migration

### Community 20 - "Community 20"
Cohesion: 0.22
Nodes (1): Ji

### Community 21 - "Community 21"
Cohesion: 0.28
Nodes (8): billing_address, instance (Order object), order_state_html, payment_state_html, shipping_address, shipping_state_html, swRefreshTransitions JS function, transitions_meta_url

### Community 22 - "Community 22"
Cohesion: 0.29
Nodes (1): Django settings for GC_Bridge_4 project.  Generated by 'django-admin startprojec

### Community 23 - "Community 23"
Cohesion: 0.29
Nodes (1): admin_model_permission()

### Community 24 - "Community 24"
Cohesion: 0.4
Nodes (1): b()

### Community 25 - "Community 25"
Cohesion: 0.6
Nodes (3): getClockBox(), getClockLink(), openClockChooser()

### Community 26 - "Community 26"
Cohesion: 0.5
Nodes (1): Microtech management package.

### Community 27 - "Community 27"
Cohesion: 0.5
Nodes (1): Microtech management commands.

### Community 28 - "Community 28"
Cohesion: 0.83
Nodes (3): cycleTheme(), initTheme(), setTheme()

### Community 29 - "Community 29"
Cohesion: 0.5
Nodes (2): BaseModel, Meta

### Community 30 - "Community 30"
Cohesion: 0.67
Nodes (2): main(), Run administrative tasks.

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): URL configuration for GC_Bridge_4 project.  The `urlpatterns` list routes URLs t

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): ASGI config for GC_Bridge_4 project.  It exposes the ASGI callable as a module-l

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (1): WSGI config for GC_Bridge_4 project.  It exposes the WSGI callable as a module-l

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): Migration

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (1): Migration

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (1): Migration

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (1): Migration

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (1): Migration

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (1): Migration

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (1): Migration

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (1): Migration

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (1): Migration

### Community 43 - "Community 43"
Cohesion: 1.0
Nodes (1): Migration

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (1): Migration

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (1): Migration

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (1): Migration

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (1): Migration

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (1): Migration

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (1): Migration

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (1): Migration

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (1): Migration

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (1): Migration

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (1): Migration

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): Migration

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (1): Migration

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): Migration

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Migration

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): SwissCustomsFieldDefinition

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): Migration

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Migration

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): Migration

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Migration

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Migration

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Migration

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Migration

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Migration

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Migration

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Migration

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Migration

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Migration

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (1): Migration

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): Migration

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): Migration

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (1): Migration

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): Migration

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): Migration

### Community 86 - "Community 86"
Cohesion: 1.0
Nodes (1): Test Django admin page with a logged-in superuser.

### Community 87 - "Community 87"
Cohesion: 1.0
Nodes (1): Migration

### Community 88 - "Community 88"
Cohesion: 1.0
Nodes (1): Migration

### Community 89 - "Community 89"
Cohesion: 1.0
Nodes (1): Migration

### Community 90 - "Community 90"
Cohesion: 1.0
Nodes (1): Migration

### Community 91 - "Community 91"
Cohesion: 1.0
Nodes (1): Migration

### Community 92 - "Community 92"
Cohesion: 1.0
Nodes (1): Migration

### Community 93 - "Community 93"
Cohesion: 1.0
Nodes (1): Migration

### Community 94 - "Community 94"
Cohesion: 1.0
Nodes (1): Migration

### Community 95 - "Community 95"
Cohesion: 1.0
Nodes (1): Migration

### Community 96 - "Community 96"
Cohesion: 1.0
Nodes (1): Migration

### Community 97 - "Community 97"
Cohesion: 1.0
Nodes (1): Migration

### Community 98 - "Community 98"
Cohesion: 1.0
Nodes (1): Migration

### Community 99 - "Community 99"
Cohesion: 1.0
Nodes (1): Migration

## Knowledge Gaps
- **100 isolated node(s):** `Run administrative tasks.`, `Django settings for GC_Bridge_4 project.  Generated by 'django-admin startprojec`, `URL configuration for GC_Bridge_4 project.  The `urlpatterns` list routes URLs t`, `ASGI config for GC_Bridge_4 project.  It exposes the ASGI callable as a module-l`, `WSGI config for GC_Bridge_4 project.  It exposes the WSGI callable as a module-l` (+95 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 19`** (9 nodes): `0001_initial.py`, `0001_initial.py`, `0001_initial.py`, `0001_initial.py`, `0001_initial.py`, `Migration`, `0001_initial.py`, `0001_initial.py`, `0001_initial.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 20`** (9 nodes): `Ji`, `.acquireContext()`, `.addEventListener()`, `.getDevicePixelRatio()`, `.getMaximumSize()`, `.isAttached()`, `.releaseContext()`, `.removeEventListener()`, `.updateConfig()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 22`** (7 nodes): `env_bool()`, `env_list()`, `env_url()`, `settings.py`, `Django settings for GC_Bridge_4 project.  Generated by 'django-admin startprojec`, `sidebar_model_add_permission()`, `sidebar_model_view_permission()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 23`** (7 nodes): `.has_perm()`, `admin_button_loader_script()`, `admin_button_loader_style()`, `admin_model_permission()`, `environment_callback()`, `unfold.py`, `superuser_only()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (5 nodes): `a()`, `b()`, `c()`, `u()`, `alpine.resize.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (4 nodes): `__init__.py`, `Microtech management package.`, `__init__.py`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (4 nodes): `Microtech management commands.`, `__init__.py`, `__init__.py`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (4 nodes): `base.py`, `__init__.py`, `BaseModel`, `Meta`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (3 nodes): `main()`, `Run administrative tasks.`, `manage.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (2 nodes): `urls.py`, `URL configuration for GC_Bridge_4 project.  The `urlpatterns` list routes URLs t`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (2 nodes): `asgi.py`, `ASGI config for GC_Bridge_4 project.  It exposes the ASGI callable as a module-l`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (2 nodes): `wsgi.py`, `WSGI config for GC_Bridge_4 project.  It exposes the WSGI callable as a module-l`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (2 nodes): `Migration`, `0013_productimage.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (2 nodes): `Migration`, `0007_category_name_de_category_name_en_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (2 nodes): `Migration`, `0016_alter_productimage_order.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (2 nodes): `Migration`, `0025_alter_category_parent.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (2 nodes): `Migration`, `0023_alter_category_options_category_description_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (2 nodes): `Migration`, `0009_price_special_percentage.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (2 nodes): `Migration`, `0006_alter_price_options.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (2 nodes): `Migration`, `0012_product_customs_tariff_number_product_weight_gross_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (2 nodes): `Migration`, `0022_priceincreaseitem_last_changed_at_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (2 nodes): `Migration`, `0018_priceincrease_priceincreaseitem.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (2 nodes): `Migration`, `0004_alter_product_options.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (2 nodes): `Migration`, `0002_image_tax_alter_product_options_product_erp_nr_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (2 nodes): `Migration`, `0017_pricehistory.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (2 nodes): `Migration`, `0008_alter_category_options_alter_image_options_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (2 nodes): `Migration`, `0020_alter_priceincreaseitem_new_rebate_price.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (2 nodes): `Migration`, `0021_alter_priceincreaseitem_new_price.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (2 nodes): `Migration`, `0024_category_sort_order.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (2 nodes): `Migration`, `0019_alter_priceincreaseitem_new_price_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (2 nodes): `Migration`, `0015_propertygroup_propertyvalue_productproperty_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (2 nodes): `Migration`, `0014_product_shopware_image_sync_hash.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (2 nodes): `Migration`, `0010_tax_shopware_id.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (2 nodes): `Migration`, `0003_alter_shopwaresettings_options_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (2 nodes): `Migration`, `0002_sales_channel_pricing_fields.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (2 nodes): `Migration`, `0004_shopwareconnection.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (2 nodes): `customs_fields.py`, `SwissCustomsFieldDefinition`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (2 nodes): `0018_microtechorderrulecondition_operator.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (2 nodes): `0016_microtechorderruledjangofield.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (2 nodes): `0010_remove_microtechorderruleconditionsource_dataset_field_and_more.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (2 nodes): `0020_alter_microtechswisscustomsfieldmapping_static_value.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (2 nodes): `0017_microtechorderrulecondition_django_field.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (2 nodes): `0005_remove_microtechorderrule_add_payment_position_and_more.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (2 nodes): `0002_microtechsettings_default_versandart_id_and_more.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (2 nodes): `0007_delete_microtechjob.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (2 nodes): `0019_microtechswisscustomsfieldmapping.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (2 nodes): `0008_microtechorderruleactiontarget_and_more.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (2 nodes): `0014_alter_microtechorderruleoperator_engine_operator.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (2 nodes): `0015_alter_microtechorderruleoperator_engine_operator.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (2 nodes): `0012_microtechjob.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (2 nodes): `0013_alter_microtechorderruleoperator_engine_operator.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (2 nodes): `0003_microtechorderrule.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (2 nodes): `0006_microtechjob.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (2 nodes): `0004_microtechorderrule_condition_logic_and_more.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (2 nodes): `0009_microtechdatasetcatalog_microtechdatasetfield_and_more.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 86`** (2 nodes): `admin_test.py`, `Test Django admin page with a logged-in superuser.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 87`** (2 nodes): `0002_alter_address_options_alter_customer_options_and_more.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 88`** (2 nodes): `0004_remove_mappeiproductmapping_factor.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 89`** (2 nodes): `0002_mappeiproduct_image_url.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 90`** (2 nodes): `0003_mappeiproduct_description.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 91`** (2 nodes): `0005_mappeiproduct_products_and_more.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 92`** (2 nodes): `0002_airewritejob_is_archived.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 93`** (2 nodes): `0005_add_bridge_day_and_vacation_entitlement.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 94`** (2 nodes): `0003_schoolholiday.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 95`** (2 nodes): `0004_leaverequest_calculated_days.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 96`** (2 nodes): `0002_companyholiday_holidaycalendar_and_more.py`, `Migration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 97`** (2 nodes): `Migration`, `0002_alter_order_customer.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 98`** (2 nodes): `Migration`, `0004_alter_order_options_alter_orderdetail_options_and_more.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 99`** (2 nodes): `Migration`, `0003_order_erp_order_id.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `filter()` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 11`, `Community 12`, `Community 13`, `Community 17`, `Community 18`?**
  _High betweenness centrality (0.222) - this node is a cross-community bridge._
- **Why does `get()` connect `Community 0` to `Community 1`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 8`, `Community 11`, `Community 12`, `Community 13`, `Community 15`, `Community 17`, `Community 18`, `Community 23`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Why does `set()` connect `Community 0` to `Community 1`, `Community 4`, `Community 5`, `Community 7`, `Community 8`, `Community 10`, `Community 11`, `Community 12`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Are the 278 inferred relationships involving `get()` (e.g. with `.get_context_data()` and `._build_ai_rewrite_field_targets_json()`) actually correct?**
  _`get()` has 278 INFERRED edges - model-reasoned connections that need verification._
- **Are the 243 inferred relationships involving `filter()` (e.g. with `.formfield_for_foreignkey()` and `.__init__()`) actually correct?**
  _`filter()` has 243 INFERRED edges - model-reasoned connections that need verification._
- **Are the 114 inferred relationships involving `create()` (e.g. with `._create_history_entry()` and `.test_set_special_price_bulk_updates_price()`) actually correct?**
  _`create()` has 114 INFERRED edges - model-reasoned connections that need verification._
- **Are the 100 inferred relationships involving `Product` (e.g. with `FullWidthHeadingBar` and `StorageInline`) actually correct?**
  _`Product` has 100 INFERRED edges - model-reasoned connections that need verification._