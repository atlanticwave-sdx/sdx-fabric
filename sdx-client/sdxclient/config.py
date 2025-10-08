import os
def get_base_url():
    sdx_base_url = os.getenv("SDX_BASE_URL")
    if not sdx_base_url:
        raise EnvironmentError("SDX_BASE_URL is not defined.")
    return sdx_base_url
# optional back-compat:
BASE_URL = get_base_url()

