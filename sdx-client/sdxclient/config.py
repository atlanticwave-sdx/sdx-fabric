import os

BASE_URL = os.getenv("SDX_BASE_URL")
if not BASE_URL:
    raise RuntimeError("Missing SDX_BASE_URL — set it to your target API (test or prod).")

