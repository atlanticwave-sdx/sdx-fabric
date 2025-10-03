# config.py
import os

# BASE_URL = "https://sdxapi.atlanticwave-sdx.ai"
BASE_URL = os.getenv(
    "SDX_BASE_URL",  # environment variable if defined
    "https://sdxapi.atlanticwave-sdx.ai"  # default (prod)
)
