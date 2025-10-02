# config.py
import os

# BASE_URL = "https://sdxapi.atlanticwave-sdx.ai"
BASE_URL = os.getenv(
    "SDX_BASE_URL",  # environment variable if defined
    "http://190.103.184.194"  # default (test)
)
