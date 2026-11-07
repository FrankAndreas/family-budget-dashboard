"""Architecture review 2026-11-07: the *_api.py modules only hold routes. Rules other code needs live in plain modules
(bookings, ownership, assets, planned_costs, common_budget, wishes, emails, privacy, ...), so no module imports a
router module; main.py alone puts them together."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "backend" / "app"
ROUTERS = {p.stem for p in APP.glob("*_api.py")}


def imported_modules(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                names.add(node.module.split(".")[0])
            else:
                names.update(alias.name for alias in node.names)
    return names


def test_only_main_imports_router_modules():
    offenders = {
        path.name: sorted(imported_modules(path) & ROUTERS)
        for path in APP.glob("*.py")
        if path.name != "main.py" and imported_modules(path) & ROUTERS
    }
    assert offenders == {}


def test_every_router_module_is_registered():
    registered = imported_modules(APP / "main.py")
    assert ROUTERS <= registered
