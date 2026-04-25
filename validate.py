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
    service_data = load_json("Service_Keywords.json")
    seo_data = load_json("SEO_Keywords.json")
    location_data = load_json("location.json")
    property_type_data = load_json("property_type.json")

    assert list(seo_data["services"].keys()) == list(service_data["services"].keys()), (
        "SEO services are not synced with Service_Keywords services"
    )
    assert list(main.SERVICE_STATE_FILES.keys()) == list(service_data["services"].keys()), (
        "SERVICE_STATE_FILES is not synced with Service_Keywords services"
    )

    for service_name in service_data["services"]:
        assert seo_data["services"][service_name], f"{service_name} SEO keywords are empty"
        assert service_data["services"][service_name]["focus_categories"], f"{service_name} focus categories are empty"

    for html_path in ("app.html", "public/app.html", "public/index.html"):
        html = (ROOT / html_path).read_text(encoding="utf-8")
        service_options = extract_js_json(html, "SERVICE_OPTIONS")
        location_options = extract_js_json(html, "LOCATION_DATA")
        property_type_options = extract_js_json(html, "PROPERTY_TYPE_OPTIONS")
        review_char_limit_options = extract_js_json(html, "REVIEW_CHAR_LIMIT_OPTIONS")

        assert service_options == list(service_data["services"].keys()), f"{html_path} SERVICE_OPTIONS is not synced"
        assert location_options == location_data, f"{html_path} LOCATION_DATA is not synced"
        assert property_type_options == list(property_type_data.keys()), f"{html_path} PROPERTY_TYPE_OPTIONS is not synced"
        assert review_char_limit_options == list(main.REVIEW_CHAR_LIMIT_OPTIONS), (
            f"{html_path} REVIEW_CHAR_LIMIT_OPTIONS is not synced"
        )
        print(f"OK {html_path} data sync")


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
            "number_of_cameras": 4 if service_name in main.CAMERA_DETAIL_SERVICES else "",
            "camera_brand": "Hikvision" if service_name in main.CAMERA_DETAIL_SERVICES else "",
            "seo_keyword": selected_inputs["seo_keyword"],
            "focus_1": selected_inputs["focus_1"],
            "focus_2": selected_inputs["focus_2"],
            "tone_rule": selected_inputs["tone_rule"],
            "perspective_rule": selected_inputs["perspective_rule"],
            "review_structure_rule": selected_inputs["review_structure_rule"],
            "property_location_rule": selected_inputs["property_location_rule"],
            "company_name_rule": selected_inputs["company_name_rule"],
            "avoid_words_rule": selected_inputs["avoid_words_rule"],
            "camera_detail_rule": main.get_camera_detail_rule(
                selected_service=service_name,
                number_of_cameras=4 if service_name in main.CAMERA_DETAIL_SERVICES else None,
                camera_brand="Hikvision" if service_name in main.CAMERA_DETAIL_SERVICES else "",
            ),
            "character_limit_rule": main.get_character_limit_rule(400),
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
