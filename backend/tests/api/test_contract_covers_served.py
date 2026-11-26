"""Every operation the API serves is in contracts/openapi.yaml, with the same operationId."""

from pathlib import Path

import yaml

from app.main import API_PREFIX, app

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"
METHODS = {"get", "post", "put", "patch", "delete"}


def operations(paths: dict, prefix: str = "") -> dict[tuple[str, str], str | None]:
    return {
        (method.upper(), path.removeprefix(prefix)): op.get("operationId")
        for path, item in paths.items()
        for method, op in item.items()
        if method in METHODS
    }


def test_every_served_operation_is_in_the_contract() -> None:
    contract = operations(yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["paths"])
    served = {
        key: op_id
        for key, op_id in operations(app.openapi()["paths"], API_PREFIX).items()
        if key[1] != "/health"
    }
    missing = sorted(set(served) - set(contract))
    assert missing == []
    renamed = {k: (served[k], contract[k]) for k in served if served[k] != contract[k]}
    assert renamed == {}
