import certifi
import os
import sys

if getattr(sys, "frozen", False):
    os.environ["SSL_CERT_FILE"] = certifi.where()

from carveracontroller.main import main
from carveracontroller.translation import tr

if __name__ == "__main__":
    main()
