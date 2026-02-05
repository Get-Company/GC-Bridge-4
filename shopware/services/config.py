import os


class ConfShopware6ApiBase:
    shopware_admin_api_url = os.getenv("SHOPWARE6_ADMIN_API_URL", "")
    client_id = os.getenv("SHOPWARE6_ID", "")
    client_secret = os.getenv("SHOPWARE6_SECRET", "")
    grant_type = os.getenv("SHOPWARE6_GRANT_TYPE", "resource_owner")
    username = os.getenv("SHOPWARE6_USER", "")
    password = os.getenv("SHOPWARE6_PASSWORD", "")
