from __future__ import annotations

import ast
import json
import re
import sys
import types
from pathlib import Path

try:
    import main
except ModuleNotFoundError as exc:
    if exc.name != "openai":
        raise
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub
    import main


ROOT = Path(__file__).resolve().parent


def load_json(filename: str) -> dict:
    return json.loads((ROOT / filename).read_text(encoding="utf-8"))


def check_json_files() -> None:
    for path in sorted(ROOT.rglob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
        print(f"OK JSON {path.relative_to(ROOT)}")


def check_python_files() -> None:
    for path in sorted(ROOT.rglob("*.py")):
        if ".venv" in path.parts or "venv" in path.parts:
            continue
        ast.parse(path.read_text(encoding="utf-8"))
        print(f"OK PY {path.relative_to(ROOT)}")


def extract_js_json(html: str, variable_name: str):
    pattern = rf"const {re.escape(variable_name)} = ([\s\S]*?);"
    match = re.search(pattern, html)
    if not match:
        raise AssertionError(f"{variable_name} not found in app.html")
    return json.loads(match.group(1))


def check_frontend_data_sync() -> None:
    html = (ROOT / "app.html").read_text(encoding="utf-8")
    service_data = load_json("Service_Keywords.json")
    location_data = load_json("location.json")
    property_type_data = load_json("property_type.json")

    service_options = extract_js_json(html, "SERVICE_OPTIONS")
    location_options = extract_js_json(html, "LOCATION_DATA")
    property_type_options = extract_js_json(html, "PROPERTY_TYPE_OPTIONS")

    assert service_options == list(service_data["services"].keys()), "SERVICE_OPTIONS is not synced"
    assert location_options == location_data, "LOCATION_DATA is not synced"
    assert property_type_options == list(property_type_data.keys()), "PROPERTY_TYPE_OPTIONS is not synced"
    print("OK app.html data sync")


def check_prompt_rendering() -> None:
    seo_data = load_json("SEO_Keywords.json")
    service_data = load_json("Service_Keywords.json")
    user_template = (ROOT / "user.txt").read_text(encoding="utf-8")

    for service_name in main.SERVICE_STATE_FILES:
        selected_inputs = main.get_next_inputs(service_name, main.DEFAULT_STATE.copy(), seo_data, service_data)
        prompt_values = {
            "selected_service": service_name,
            "area": "Ahmedabad",
            "subarea": "Satellite",
            "property_type": "office",
            "number_of_cameras": 4 if service_name == "CCTV Installation" else "",
            "camera_brand": "Hikvision" if service_name == "CCTV Installation" else "",
            "seo_keyword": selected_inputs["seo_keyword"],
            "focus_1": selected_inputs["focus_1"],
            "focus_2": selected_inputs["focus_2"],
            "tone_rule": selected_inputs["tone_rule"],
            "perspective_rule": selected_inputs["perspective_rule"],
            "review_structure_rule": selected_inputs["review_structure_rule"],
            "property_location_rule": selected_inputs["property_location_rule"],
            "company_name_rule": selected_inputs["company_name_rule"],
            "avoid_words_rule": selected_inputs["avoid_words_rule"],
            "recent_reviews_block": "None",
            "review_char_limit": 400,
        }
        main.render_prompt(user_template, prompt_values)
        print(f"OK prompt {service_name}")


def main_cli() -> None:
    check_json_files()
    check_python_files()
    check_frontend_data_sync()
    check_prompt_rendering()
    print("All validation checks passed.")


if __name__ == "__main__":
    main_cli()
