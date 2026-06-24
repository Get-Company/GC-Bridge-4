Batch 5 | Produkte: ['104006', '104011', '104011+2H', '104014', '104014-1', '104016', '104025', '104030', '104031', '104032']
Traceback (most recent call last):
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 654, in _request
response.raise_for_status()  # type: ignore[possibly-undefined]
^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/httpx/_models.py", line 829, in raise_for_status
raise HTTPStatusError(message, request=request, response=self)
httpx.HTTPStatusError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/97d981c8969c07a32f7fcd678739bf6c/upload?extension=png&fileName=01_orgaablaeufe_Set5'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
File "/app/shopware/management/commands/shopware_force_product_image_uploads.py", line 283, in _run_upload_step
media_sync_service.sync_media_assets(
File "/app/shopware/services/product_media.py", line 89, in sync_media_assets
product_service.upload_media_from_url(
File "/app/shopware/services/product.py", line 264, in upload_media_from_url
return self.request_post(
^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 123, in request_post
result = self._request_with_retry(
^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 37, in _request_with_retry
return request_method(*args, **kwargs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 221, in request_post
response_dict = self._make_request(
^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 552, in _make_request
raise exc
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 516, in _make_request
response = self._request(
^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 657, in _request
raise ShopwareAPIError(f"{exc}{detailed_error}") from exc
lib_shopware6_api_base.conf_shopware6_api_base_classes.ShopwareAPIError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/97d981c8969c07a32f7fcd678739bf6c/upload?extension=png&fileName=01_orgaablaeufe_Set5'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 : {"errors":[{"status":"400","code":"CONTENT__MEDIA_CANNOT_OPEN_SOURCE_STREAM_TO_READ","title":"Bad Request","detail":"Cannot open source stream to read from https:\/\/assets.classei.de\/img\/01_orgaablaeufe_Set5.png.","meta":{"parameters":{"url":"https:\/\/assets.classei.de\/img\/01_orgaablaeufe_Set5.png"}},"trace":[{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":172,"function":"cannotOpenSourceStreamToRead","class":"Shopware\\Core\\Content\\Media\\MediaException","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":68,"function":"openSourceFromUrl","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":95,"function":"fetchFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/MediaService.php","line":112,"function":"fetchFileFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/Api\/MediaUploadController.php","line":56,"function":"fetchFile","class":"Shopware\\Core\\Content\\Media\\MediaService","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":183,"function":"upload","class":"Shopware\\Core\\Content\\Media\\Api\\MediaUploadController","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":76,"function":"handleRaw","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpKernel.php","line":72,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/SubRequestHandler.php","line":86,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":466,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\SubRequestHandler","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":268,"function":"forward","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":282,"function":"pass","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":202,"function":"invalidate","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpCacheKernel.php","line":61,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Kernel.php","line":129,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpCacheKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/runtime\/Runner\/Symfony\/HttpKernelRunner.php","line":35,"function":"handle","class":"Shopware\\Core\\Kernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php","line":32,"function":"run","class":"Symfony\\Component\\Runtime\\Runner\\Symfony\\HttpKernelRunner","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/public\/index.php","line":11,"args":["\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php"],"function":"require_once"}]}]}


Batch 10 | Produkte: ['14IT18/Z', '14IT20/Z', '14IT78', '16200', '16200S', '16210', '180002', '180003', '180006', '180011']
Traceback (most recent call last):
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 654, in _request
response.raise_for_status()  # type: ignore[possibly-undefined]
^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/httpx/_models.py", line 829, in raise_for_status
raise HTTPStatusError(message, request=request, response=self)
httpx.HTTPStatusError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/7f805cfb3ca0fd62943dad65caf5dc8b/upload?extension=png&fileName=16200'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
File "/app/shopware/management/commands/shopware_force_product_image_uploads.py", line 283, in _run_upload_step
media_sync_service.sync_media_assets(
File "/app/shopware/services/product_media.py", line 89, in sync_media_assets
product_service.upload_media_from_url(
File "/app/shopware/services/product.py", line 264, in upload_media_from_url
return self.request_post(
^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 123, in request_post
result = self._request_with_retry(
^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 37, in _request_with_retry
return request_method(*args, **kwargs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 221, in request_post
response_dict = self._make_request(
^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 552, in _make_request
raise exc
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 516, in _make_request
response = self._request(
^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 657, in _request
raise ShopwareAPIError(f"{exc}{detailed_error}") from exc
lib_shopware6_api_base.conf_shopware6_api_base_classes.ShopwareAPIError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/7f805cfb3ca0fd62943dad65caf5dc8b/upload?extension=png&fileName=16200'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 : {"errors":[{"status":"400","code":"CONTENT__MEDIA_CANNOT_OPEN_SOURCE_STREAM_TO_READ","title":"Bad Request","detail":"Cannot open source stream to read from https:\/\/assets.classei.de\/img\/16200.png.","meta":{"parameters":{"url":"https:\/\/assets.classei.de\/img\/16200.png"}},"trace":[{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":172,"function":"cannotOpenSourceStreamToRead","class":"Shopware\\Core\\Content\\Media\\MediaException","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":68,"function":"openSourceFromUrl","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":95,"function":"fetchFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/MediaService.php","line":112,"function":"fetchFileFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/Api\/MediaUploadController.php","line":56,"function":"fetchFile","class":"Shopware\\Core\\Content\\Media\\MediaService","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":183,"function":"upload","class":"Shopware\\Core\\Content\\Media\\Api\\MediaUploadController","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":76,"function":"handleRaw","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpKernel.php","line":72,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/SubRequestHandler.php","line":86,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":466,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\SubRequestHandler","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":268,"function":"forward","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":282,"function":"pass","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":202,"function":"invalidate","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpCacheKernel.php","line":61,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Kernel.php","line":129,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpCacheKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/runtime\/Runner\/Symfony\/HttpKernelRunner.php","line":35,"function":"handle","class":"Shopware\\Core\\Kernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php","line":32,"function":"run","class":"Symfony\\Component\\Runtime\\Runner\\Symfony\\HttpKernelRunner","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/public\/index.php","line":11,"args":["\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php"],"function":"require_once"}]}]}


Batch 13 | Produkte: ['204013U', '204021', '204021-ALT', '204045', '204045/00', '204045/00-10', '204045/01', '204045/01-10', '204045/02', '204045/02-10']
Traceback (most recent call last):
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 654, in _request
response.raise_for_status()  # type: ignore[possibly-undefined]
^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/httpx/_models.py", line 829, in raise_for_status
raise HTTPStatusError(message, request=request, response=self)
httpx.HTTPStatusError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/3639377a252b08bff32a6bda803c15cf/upload?extension=png&fileName=204045-00'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
File "/app/shopware/management/commands/shopware_force_product_image_uploads.py", line 283, in _run_upload_step
media_sync_service.sync_media_assets(
File "/app/shopware/services/product_media.py", line 89, in sync_media_assets
product_service.upload_media_from_url(
File "/app/shopware/services/product.py", line 264, in upload_media_from_url
return self.request_post(
^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 123, in request_post
result = self._request_with_retry(
^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 37, in _request_with_retry
return request_method(*args, **kwargs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 221, in request_post
response_dict = self._make_request(
^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 552, in _make_request
raise exc
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 516, in _make_request
response = self._request(
^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 657, in _request
raise ShopwareAPIError(f"{exc}{detailed_error}") from exc
lib_shopware6_api_base.conf_shopware6_api_base_classes.ShopwareAPIError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/3639377a252b08bff32a6bda803c15cf/upload?extension=png&fileName=204045-00'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 : {"errors":[{"status":"400","code":"CONTENT__MEDIA_CANNOT_OPEN_SOURCE_STREAM_TO_READ","title":"Bad Request","detail":"Cannot open source stream to read from https:\/\/assets.classei.de\/img\/204045-00.png.","meta":{"parameters":{"url":"https:\/\/assets.classei.de\/img\/204045-00.png"}},"trace":[{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":172,"function":"cannotOpenSourceStreamToRead","class":"Shopware\\Core\\Content\\Media\\MediaException","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":68,"function":"openSourceFromUrl","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":95,"function":"fetchFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/MediaService.php","line":112,"function":"fetchFileFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/Api\/MediaUploadController.php","line":56,"function":"fetchFile","class":"Shopware\\Core\\Content\\Media\\MediaService","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":183,"function":"upload","class":"Shopware\\Core\\Content\\Media\\Api\\MediaUploadController","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":76,"function":"handleRaw","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpKernel.php","line":72,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/SubRequestHandler.php","line":86,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":466,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\SubRequestHandler","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":268,"function":"forward","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":282,"function":"pass","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":202,"function":"invalidate","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpCacheKernel.php","line":61,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Kernel.php","line":129,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpCacheKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/runtime\/Runner\/Symfony\/HttpKernelRunner.php","line":35,"function":"handle","class":"Shopware\\Core\\Kernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php","line":32,"function":"run","class":"Symfony\\Component\\Runtime\\Runner\\Symfony\\HttpKernelRunner","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/public\/index.php","line":11,"args":["\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php"],"function":"require_once"}]}]}


Batch 14 | Produkte: ['204045/03', '204045/03-10', '204045/06', '204045/06-10', '204045S20', '204045S5', '204109', '204109A20', '204109A22', '204109E24']
Traceback (most recent call last):
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 654, in _request
response.raise_for_status()  # type: ignore[possibly-undefined]
^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/httpx/_models.py", line 829, in raise_for_status
raise HTTPStatusError(message, request=request, response=self)
httpx.HTTPStatusError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/51a415f1915414915af5a473c455ca1e/upload?extension=jpg&fileName=204045S20'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
File "/app/shopware/management/commands/shopware_force_product_image_uploads.py", line 283, in _run_upload_step
media_sync_service.sync_media_assets(
File "/app/shopware/services/product_media.py", line 89, in sync_media_assets
product_service.upload_media_from_url(
File "/app/shopware/services/product.py", line 264, in upload_media_from_url
return self.request_post(
^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 123, in request_post
result = self._request_with_retry(
^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 37, in _request_with_retry
return request_method(*args, **kwargs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 221, in request_post
response_dict = self._make_request(
^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 552, in _make_request
raise exc
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 516, in _make_request
response = self._request(
^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 657, in _request
raise ShopwareAPIError(f"{exc}{detailed_error}") from exc
lib_shopware6_api_base.conf_shopware6_api_base_classes.ShopwareAPIError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/51a415f1915414915af5a473c455ca1e/upload?extension=jpg&fileName=204045S20'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 : {"errors":[{"status":"400","code":"CONTENT__MEDIA_CANNOT_OPEN_SOURCE_STREAM_TO_READ","title":"Bad Request","detail":"Cannot open source stream to read from https:\/\/assets.classei.de\/img\/204045S20.jpg.","meta":{"parameters":{"url":"https:\/\/assets.classei.de\/img\/204045S20.jpg"}},"trace":[{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":172,"function":"cannotOpenSourceStreamToRead","class":"Shopware\\Core\\Content\\Media\\MediaException","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":68,"function":"openSourceFromUrl","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":95,"function":"fetchFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/MediaService.php","line":112,"function":"fetchFileFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/Api\/MediaUploadController.php","line":56,"function":"fetchFile","class":"Shopware\\Core\\Content\\Media\\MediaService","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":183,"function":"upload","class":"Shopware\\Core\\Content\\Media\\Api\\MediaUploadController","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":76,"function":"handleRaw","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpKernel.php","line":72,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/SubRequestHandler.php","line":86,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":466,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\SubRequestHandler","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":268,"function":"forward","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":282,"function":"pass","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":202,"function":"invalidate","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpCacheKernel.php","line":61,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Kernel.php","line":129,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpCacheKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/runtime\/Runner\/Symfony\/HttpKernelRunner.php","line":35,"function":"handle","class":"Shopware\\Core\\Kernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php","line":32,"function":"run","class":"Symfony\\Component\\Runtime\\Runner\\Symfony\\HttpKernelRunner","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/public\/index.php","line":11,"args":["\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php"],"function":"require_once"}]}]}


Batch 19 | Produkte: ['214025', '214045', '214045-10', '214123', '214123-100', '214123-1U', '214123-20', '214123B30', '214123BAM04', '214123BAM06']
Traceback (most recent call last):
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 654, in _request
response.raise_for_status()  # type: ignore[possibly-undefined]
^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/httpx/_models.py", line 829, in raise_for_status
raise HTTPStatusError(message, request=request, response=self)
httpx.HTTPStatusError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/afc50c9a61f132b45abe50579c0a3fe8/upload?extension=png&fileName=fertigset_900050'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
File "/app/shopware/management/commands/shopware_force_product_image_uploads.py", line 283, in _run_upload_step
media_sync_service.sync_media_assets(
File "/app/shopware/services/product_media.py", line 89, in sync_media_assets
product_service.upload_media_from_url(
File "/app/shopware/services/product.py", line 264, in upload_media_from_url
return self.request_post(
^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 123, in request_post
result = self._request_with_retry(
^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 37, in _request_with_retry
return request_method(*args, **kwargs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 221, in request_post
response_dict = self._make_request(
^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 552, in _make_request
raise exc
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 516, in _make_request
response = self._request(
^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 657, in _request
raise ShopwareAPIError(f"{exc}{detailed_error}") from exc
lib_shopware6_api_base.conf_shopware6_api_base_classes.ShopwareAPIError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/afc50c9a61f132b45abe50579c0a3fe8/upload?extension=png&fileName=fertigset_900050'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 : {"errors":[{"status":"400","code":"CONTENT__MEDIA_CANNOT_OPEN_SOURCE_STREAM_TO_READ","title":"Bad Request","detail":"Cannot open source stream to read from https:\/\/assets.classei.de\/img\/fertigset_900050.png.","meta":{"parameters":{"url":"https:\/\/assets.classei.de\/img\/fertigset_900050.png"}},"trace":[{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":172,"function":"cannotOpenSourceStreamToRead","class":"Shopware\\Core\\Content\\Media\\MediaException","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":68,"function":"openSourceFromUrl","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":95,"function":"fetchFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/MediaService.php","line":112,"function":"fetchFileFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/Api\/MediaUploadController.php","line":56,"function":"fetchFile","class":"Shopware\\Core\\Content\\Media\\MediaService","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":183,"function":"upload","class":"Shopware\\Core\\Content\\Media\\Api\\MediaUploadController","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":76,"function":"handleRaw","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpKernel.php","line":72,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/SubRequestHandler.php","line":86,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":466,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\SubRequestHandler","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":268,"function":"forward","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":282,"function":"pass","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":202,"function":"invalidate","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpCacheKernel.php","line":61,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Kernel.php","line":129,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpCacheKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/runtime\/Runner\/Symfony\/HttpKernelRunner.php","line":35,"function":"handle","class":"Shopware\\Core\\Kernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php","line":32,"function":"run","class":"Symfony\\Component\\Runtime\\Runner\\Symfony\\HttpKernelRunner","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/public\/index.php","line":11,"args":["\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php"],"function":"require_once"}]}]}


Batch 21 | Produkte: ['224551', '224553', '224553-150', '224553-20', '224553K', '224553P', '224813', '224816', '234123', '234123-10']
Traceback (most recent call last):
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 654, in _request
response.raise_for_status()  # type: ignore[possibly-undefined]
^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/httpx/_models.py", line 829, in raise_for_status
raise HTTPStatusError(message, request=request, response=self)
httpx.HTTPStatusError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/8897a4e70235069066c214d2beab7a99/upload?extension=png&fileName=224553K'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
File "/app/shopware/management/commands/shopware_force_product_image_uploads.py", line 283, in _run_upload_step
media_sync_service.sync_media_assets(
File "/app/shopware/services/product_media.py", line 89, in sync_media_assets
product_service.upload_media_from_url(
File "/app/shopware/services/product.py", line 264, in upload_media_from_url
return self.request_post(
^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 123, in request_post
result = self._request_with_retry(
^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/shopware/services/shopware6.py", line 37, in _request_with_retry
return request_method(*args, **kwargs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 221, in request_post
response_dict = self._make_request(
^^^^^^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 552, in _make_request
raise exc
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 516, in _make_request
response = self._request(
^^^^^^^^^^^^^^
File "/app/.venv/lib/python3.12/site-packages/lib_shopware6_api_base/lib_shopware6_admin_client.py", line 657, in _request
raise ShopwareAPIError(f"{exc}{detailed_error}") from exc
lib_shopware6_api_base.conf_shopware6_api_base_classes.ShopwareAPIError: Client error '400 Bad Request' for url 'https://sw6dev.classei-shop.de/api/_action/media/8897a4e70235069066c214d2beab7a99/upload?extension=png&fileName=224553K'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 : {"errors":[{"status":"400","code":"CONTENT__MEDIA_CANNOT_OPEN_SOURCE_STREAM_TO_READ","title":"Bad Request","detail":"Cannot open source stream to read from https:\/\/assets.classei.de\/img\/224553K.png.","meta":{"parameters":{"url":"https:\/\/assets.classei.de\/img\/224553K.png"}},"trace":[{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":172,"function":"cannotOpenSourceStreamToRead","class":"Shopware\\Core\\Content\\Media\\MediaException","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":68,"function":"openSourceFromUrl","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/File\/FileFetcher.php","line":95,"function":"fetchFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/MediaService.php","line":112,"function":"fetchFileFromURL","class":"Shopware\\Core\\Content\\Media\\File\\FileFetcher","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Content\/Media\/Api\/MediaUploadController.php","line":56,"function":"fetchFile","class":"Shopware\\Core\\Content\\Media\\MediaService","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":183,"function":"upload","class":"Shopware\\Core\\Content\\Media\\Api\\MediaUploadController","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpKernel.php","line":76,"function":"handleRaw","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpKernel.php","line":72,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/SubRequestHandler.php","line":86,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":466,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\SubRequestHandler","type":"::"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":268,"function":"forward","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":282,"function":"pass","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/http-kernel\/HttpCache\/HttpCache.php","line":202,"function":"invalidate","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Framework\/Adapter\/Kernel\/HttpCacheKernel.php","line":61,"function":"handle","class":"Symfony\\Component\\HttpKernel\\HttpCache\\HttpCache","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/shopware\/core\/Kernel.php","line":129,"function":"handle","class":"Shopware\\Core\\Framework\\Adapter\\Kernel\\HttpCacheKernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/symfony\/runtime\/Runner\/Symfony\/HttpKernelRunner.php","line":35,"function":"handle","class":"Shopware\\Core\\Kernel","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php","line":32,"function":"run","class":"Symfony\\Component\\Runtime\\Runner\\Symfony\\HttpKernelRunner","type":"-\u003E"},{"file":"\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/public\/index.php","line":11,"args":["\/kunden\/106812_83250\/webseiten\/shopware\/sw6dev\/vendor\/autoload_runtime.php"],"function":"require_once"}]}]}
