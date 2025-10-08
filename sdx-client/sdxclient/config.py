import os

BASE_URL = os.getenv("SDX_BASE_URL")
if not BASE_URL:
    raise EnvironmentError(
        "SDX_BASE_URL is not defined. Set it before importing sdxclient."
    )

