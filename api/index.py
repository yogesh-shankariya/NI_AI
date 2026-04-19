from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import CACHE_LIMIT, generate_review_from_state, load_json  # noqa: E402


MAX_BODY_BYTES = 10_000
REVIEW_CHAR_LIMIT = 400


def clean_text(value: Any, max_length: int = 120) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def parse_optional_camera_count(value: Any) -> int | None:
    raw_value = clean_text(value)
    if raw_value == "":
        return None

    if not raw_value.isdigit() or int(raw_value) < 1:
        raise ValueError("Number of cameras must be a whole number.")

    return int(raw_value)


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured.")
    return value


def get_supabase_key() -> str:
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_SECRET_KEY", "").strip()
    )


def supabase_request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    supabase_url = get_required_env("SUPABASE_URL").rstrip("/")
    supabase_key = get_supabase_key()
    if not supabase_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY is not configured.")

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if method != "GET":
        headers["Prefer"] = "return=representation"

    request = urllib.request.Request(
        f"{supabase_url}/rest/v1/{path}",
        data=body,
        method=method,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase request failed ({exc.code}): {details}") from exc

    if response_body == "":
        return None
    return json.loads(response_body)


def reserve_state(service: str) -> dict[str, Any]:
    response = supabase_request("POST", "rpc/reserve_review_state", {"p_service": service})
    if isinstance(response, list):
        if not response:
            raise RuntimeError("Supabase did not return service state.")
        return response[0]
    if not isinstance(response, dict):
        raise RuntimeError("Supabase returned invalid service state.")
    return response


def fetch_recent_reviews(service: str) -> list[str]:
    encoded_service = urllib.parse.quote(service, safe="")
    query = (
        "review_history"
        "?select=review"
        f"&service=eq.{encoded_service}"
        "&order=created_at.desc"
        f"&limit={CACHE_LIMIT}"
    )
    rows = supabase_request("GET", query)
    if not isinstance(rows, list):
        return []

    reviews = [clean_text(row.get("review"), max_length=1000) for row in rows if isinstance(row, dict)]
    return [review for review in reversed(reviews) if review]


def save_review_history(payload: dict[str, Any]) -> None:
    supabase_request("POST", "review_history", payload)


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    service_data = load_json(ROOT_DIR / "Service_Keywords.json")
    location_data = load_json(ROOT_DIR / "location.json")
    property_type_data = load_json(ROOT_DIR / "property_type.json")

    service = clean_text(payload.get("service"))
    area = clean_text(payload.get("area"))
    subarea = clean_text(payload.get("subarea"))
    property_type = clean_text(payload.get("property_type") or payload.get("propertyType"))
    camera_brand = clean_text(payload.get("camera_brand") or payload.get("cameraBrand"), max_length=80)
    number_of_cameras = parse_optional_camera_count(
        payload.get("number_of_cameras") or payload.get("numberOfCameras")
    )

    if service not in service_data["services"]:
        raise ValueError("Please select a valid service.")
    if area not in location_data:
        raise ValueError("Please select a valid area.")
    if subarea not in location_data[area]:
        raise ValueError("Please select a valid subarea.")
    if property_type not in property_type_data:
        raise ValueError("Please select a valid property type.")
    if service != "CCTV Installation":
        number_of_cameras = None
        camera_brand = ""

    return {
        "service": service,
        "area": area,
        "subarea": subarea,
        "property_type": property_type,
        "number_of_cameras": number_of_cameras,
        "camera_brand": camera_brand,
    }


def generate_review(payload: dict[str, Any]) -> dict[str, Any]:
    total_start = time.perf_counter()
    timings_ms: dict[str, int] = {}

    step_start = time.perf_counter()
    values = validate_payload(payload)
    timings_ms["validate"] = round((time.perf_counter() - step_start) * 1000)

    step_start = time.perf_counter()
    state = reserve_state(values["service"])
    timings_ms["reserve_state"] = round((time.perf_counter() - step_start) * 1000)

    step_start = time.perf_counter()
    recent_reviews = fetch_recent_reviews(values["service"])
    timings_ms["fetch_recent_reviews"] = round((time.perf_counter() - step_start) * 1000)

    step_start = time.perf_counter()
    result = generate_review_from_state(
        base_dir=ROOT_DIR,
        selected_service=values["service"],
        area=values["area"],
        subarea=values["subarea"],
        property_type=values["property_type"],
        number_of_cameras=values["number_of_cameras"],
        camera_brand=values["camera_brand"],
        review_char_limit=REVIEW_CHAR_LIMIT,
        state=state,
        recent_reviews=recent_reviews,
        api_key=get_required_env("OPENAI_API_KEY"),
    )
    timings_ms["openai_generate"] = round((time.perf_counter() - step_start) * 1000)

    selected_inputs = result["selected_inputs"]
    history_payload = {
        **values,
        "seo_keyword": selected_inputs["seo_keyword"],
        "focus_1": selected_inputs["focus_1"],
        "focus_2": selected_inputs["focus_2"],
        "tone_rule": selected_inputs["tone_rule"],
        "perspective_rule": selected_inputs["perspective_rule"],
        "property_location_rule": selected_inputs["property_location_rule"],
        "company_name_rule": selected_inputs["company_name_rule"],
        "avoid_words_rule": selected_inputs["avoid_words_rule"],
        "review": result["review"],
        "similarity": result["similarity"],
    }
    step_start = time.perf_counter()
    save_review_history(history_payload)
    timings_ms["save_review_history"] = round((time.perf_counter() - step_start) * 1000)
    timings_ms["total"] = round((time.perf_counter() - total_start) * 1000)

    print("generate_review timings_ms=" + json.dumps(timings_ms, sort_keys=True))

    return {
        "review": result["review"],
        "meta": {
            "seo_keyword": selected_inputs["seo_keyword"],
            "focus_1": selected_inputs["focus_1"],
            "focus_2": selected_inputs["focus_2"],
            "perspective_rule": selected_inputs["perspective_rule"],
            "timings_ms": timings_ms,
        },
    }


def health_check() -> dict[str, Any]:
    start = time.perf_counter()
    rows = supabase_request("GET", "service_state?select=service&limit=1")
    return {
        "ok": True,
        "supabase": isinstance(rows, list),
        "elapsed_ms": round((time.perf_counter() - start) * 1000),
    }


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_common_headers()
        self.end_headers()

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.send_common_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                raise ValueError("Request body is required.")
            if content_length > MAX_BODY_BYTES:
                raise ValueError("Request body is too large.")

            raw_body = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(raw_body)
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")

            response = generate_review(payload)
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            print(traceback.format_exc())
            self.send_json(500, {"error": f"Could not generate review: {exc}"})
        else:
            self.send_json(200, response)

    def do_GET(self) -> None:
        if self.path.startswith("/api/health"):
            try:
                self.send_json(200, health_check())
            except Exception as exc:
                print(traceback.format_exc())
                self.send_json(500, {"ok": False, "error": str(exc)})
            return

        self.send_json(200, {"ok": True})

    def send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", os.getenv("ALLOWED_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, status_code: int, data: dict[str, Any]) -> None:
        response_body = json.dumps(data).encode("utf-8")

        self.send_response(status_code)
        self.send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)
