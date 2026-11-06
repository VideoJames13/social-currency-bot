"""Entry point: `python -m bot`."""

import logging
import sys

from .config import OWNER_ID, TOKEN


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    if not TOKEN:
        sys.exit("DISCORD_TOKEN is missing. Copy .env.example to .env and paste your bot token.")
    if OWNER_ID is None:
        sys.exit("OWNER_ID is missing or invalid in .env.")

    from .client import BucksBot

    BucksBot().run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
