#!/bin/bash
# Start the backend locally with receipt reading on (issue #56). The Infomaniak token and product ID come from
# the password store and only live in this process's environment; nothing here prints them.
set -euo pipefail
set +x
cd "$(dirname "$0")/../backend"
INFOMANIAK_AI_TOKEN="$(pass show andreas/infomaniak_ai_api_token | head -n 1)"
INFOMANIAK_AI_PRODUCT_ID="$(pass show andreas/infomaniak_ai_product_id | head -n 1)"
export INFOMANIAK_AI_TOKEN INFOMANIAK_AI_PRODUCT_ID
exec uvicorn app.main:app --reload "$@"
