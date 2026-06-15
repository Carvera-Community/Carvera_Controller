#!/bin/bash
set -e

cd "$(dirname "$0")"
cd ..

poetry sync
poetry run -- python3 -m carveracontroller
