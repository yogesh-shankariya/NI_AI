from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from openai import OpenAI


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

MODEL = "gpt-5.4"
TEMPERATURE = 2
REASONING = {"effort": "none"}

CACHE_LIMIT = 10
MAX_RETRY = 3
SIMILARITY_THRESHOLD = 0.88

SERVICE_STATE_FILES = {
    "CCTV Installation": "cctv_installation.json",
    "Wireless Intrusion Alarm System": "wireless_intrusion_alarm_system.json",
    "Video Door Phone": "video_door_phone.json",
    "Intercom System": "intercom_system.json",
}

PROPERTY_LOCATION_RULES = [
    "Mention the property type naturally in the middle of the first sentence and skip location completely.",
    "Mention the property type naturally near the end of the first sentence and skip location completely.",
    "Mention the property type naturally in the middle of the second sentence and skip location completely.",
    "Mention the property type naturally near the end of the second sentence and skip location completely.",
    "Mention one combined property type and location phrase naturally once.",
    "Mention the property type naturally near the beginning of the review and skip location completely.",
    "Mention the property type naturally in the second sentence and skip location completely.",
    "Mention the property type naturally near the end of the review and skip location completely.",
    "Mention the property type naturally once and skip location completely.",
    "Mention one combined property type and location phrase naturally once.",
]

REVIEW_STRUCTURE_RULES = [
    "Use a property-first structure. Start from the property/use case context, then connect it to the service result. Do not start with I had, I got, We had, or We got.",
    "Use a service-first structure. Start from the selected service work, then mention the property type and focus points naturally.",
    "Use a result-first structure. Start with the practical outcome or improvement, then explain the service experience.",
    "Use a team/process-first structure. Start with how the team handled checking, planning, installation, setup, or explanation.",
    "Use a location-and-company structure. If the company and location rules ask for them, include both naturally once without making the sentence sound like an ad.",
    "Use a detail-first structure. Start with a concrete service detail such as wiring, setup, coverage, configuration, explanation, or handover.",
    "Use a support-first structure. Start with guidance, response, explanation, or after-service confidence, then mention the work done.",
    "Use a recommendation-first structure. Start like a genuine customer recommendation, then include the selected service and focus points.",
    "Use a short direct structure. Keep it simple and conversational, with a different opening from recent reviews.",
    "Use a neutral summary structure. If the company and location rules ask for them, include both naturally once and avoid starting with I or we.",
]

DEFAULT_STATE = {
    "generation_count": 0,
    "seo_index": 0,
    "focus_index": 0,
    "tone_index": 0,
    "perspective_index": 0,
    "property_location_style_index": 0,
    "company_name_counter": 0,
    "avoid_words_index": 0,
    "recent_reviews": [],
    "recent_seo_keywords": [],
    "recent_focus_pairs": [],
}

TONE_RULES = [
    "Use a plain positive tone.",
    "Use a practical customer tone.",
    "Use a warm positive tone.",
    "Use a confident but natural tone.",
    "Use a service-focused positive tone.",
]

PERSPECTIVE_RULES = [
    "Use first-person singular with varied wording. You may use I, my, or me, but do not force the review to start with I got or I had.",
    "Use first-person plural with varied wording. You may use we, our, or us, but do not force the review to start with We got or We had.",
    "Use first-person singular with a different opening shape from recent reviews. Avoid repeating the same first three or four words.",
    "Use first-person plural with a different opening shape from recent reviews. Avoid repeating the same first three or four words.",
    "Use a third-person or neutral service-focused style. Do not start with I or we.",
]

AVOID_WORD_RULES = [
    "Avoid using the word good if possible.",
    "Avoid using the word nice if possible.",
    "Avoid using the phrase good experience.",
    "Avoid using the phrase very professional.",
    "Avoid using the phrase excellent service.",
    "Avoid using the phrase happy with.",
    "Avoid using the phrase satisfied with.",
    "Avoid generic praise words unless they fit very naturally.",
]

COMPANY_NAME_RULE_EVERY = 5


def load_openai_api_key(env_path: Path | None = None) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key

    if env_path is None or not env_path.exists():
        raise FileNotFoundError("OPENAI_API_KEY is not configured.")

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = re.match(r"OPENAI_API_KEY\s*[:=]\s*['\"]?(.*?)['\"]?\s*$", stripped)
        if match and match.group(1):
            api_key = match.group(1).strip()
            os.environ["OPENAI_API_KEY"] = api_key
            return api_key

    raise ValueError(f"OPENAI_API_KEY not found in {env_path}")


def load_schema(schema_path: Path):
    spec = importlib.util.spec_from_file_location("review_schema_module", schema_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load schema from {schema_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ReviewResponse


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_state(data: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(data or {})

    if "location_style_index" in data and "property_location_style_index" not in data:
        data["property_location_style_index"] = data.pop("location_style_index")

    if "perspective_index" not in data:
        data["perspective_index"] = data.get("generation_count", 0)

    merged = DEFAULT_STATE.copy()
    merged.update(data)
    return merged


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return DEFAULT_STATE.copy()

    return normalize_state(load_json(state_path))


def save_state(state_path: Path, state: dict) -> None:
    save_json(state_path, state)


def render_prompt(template: str, values: dict[str, Any]) -> str:
    missing = sorted({
        name for name in PLACEHOLDER_PATTERN.findall(template)
        if name not in values
    })
    if missing:
        raise KeyError(f"Missing prompt values for: {missing}")

    return PLACEHOLDER_PATTERN.sub(lambda match: str(values[match.group(1)]), template)


def build_recent_reviews_block(recent_reviews: list[str]) -> str:
    if not recent_reviews:
        return "None"

    return "\n".join(f"{idx}. {review}" for idx, review in enumerate(recent_reviews, start=1))


def push_limited(items: list, value: Any, limit: int) -> list:
    items = list(items)
    items.append(value)
    return items[-limit:]


def get_company_name_rule(counter: int) -> str:
    if counter % COMPANY_NAME_RULE_EVERY == 0:
        return "Mention Nilkanth Infotech naturally once."
    return "Do not mention Nilkanth Infotech or any company name."


def build_focus_pairs(selected_service: str, focus_categories: dict[str, list[str]]) -> list[tuple[str, str]]:
    if "system_quality" in focus_categories:
        primary_bucket_name = "system_quality"
    else:
        primary_bucket_name = list(focus_categories.keys())[0]

    primary_bucket = focus_categories[primary_bucket_name]
    secondary_bucket_names = [k for k in focus_categories.keys() if k != primary_bucket_name]

    if not secondary_bucket_names:
        secondary_bucket_names = [primary_bucket_name]

    pairs: list[tuple[str, str]] = []
    for i, primary in enumerate(primary_bucket):
        secondary_bucket_name = secondary_bucket_names[i % len(secondary_bucket_names)]
        secondary_bucket = focus_categories[secondary_bucket_name]
        secondary = secondary_bucket[i % len(secondary_bucket)]
        pairs.append((primary, secondary))

    return pairs


def get_next_inputs(selected_service: str, state: dict, seo_data: dict, service_data: dict) -> dict[str, Any]:
    seo_keywords = seo_data["services"][selected_service]
    focus_categories = service_data["services"][selected_service]["focus_categories"]
    focus_pairs = build_focus_pairs(selected_service, focus_categories)

    seo_keyword = seo_keywords[state["seo_index"] % len(seo_keywords)]
    focus_1, focus_2 = focus_pairs[state["focus_index"] % len(focus_pairs)]
    tone_rule = TONE_RULES[state["tone_index"] % len(TONE_RULES)]
    perspective_rule = PERSPECTIVE_RULES[state["perspective_index"] % len(PERSPECTIVE_RULES)]
    review_structure_rule = REVIEW_STRUCTURE_RULES[state["generation_count"] % len(REVIEW_STRUCTURE_RULES)]
    property_location_rule = PROPERTY_LOCATION_RULES[
        state["property_location_style_index"] % len(PROPERTY_LOCATION_RULES)
    ]
    avoid_words_rule = AVOID_WORD_RULES[state["avoid_words_index"] % len(AVOID_WORD_RULES)]
    company_name_rule = get_company_name_rule(state["company_name_counter"] + 1)

    return {
        "seo_keyword": seo_keyword,
        "focus_1": focus_1,
        "focus_2": focus_2,
        "tone_rule": tone_rule,
        "perspective_rule": perspective_rule,
        "review_structure_rule": review_structure_rule,
        "property_location_rule": property_location_rule,
        "avoid_words_rule": avoid_words_rule,
        "company_name_rule": company_name_rule,
    }


def similarity_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def max_similarity_against_history(text: str, history: list[str]) -> float:
    if not history:
        return 0.0
    return max(similarity_score(text, h) for h in history)


def extract_parsed_response(response):
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        return parsed.model_dump(mode="json") if hasattr(parsed, "model_dump") else parsed

    for item in getattr(response, "output", []) or []:
        for part in getattr(item, "content", []) or []:
            parsed = getattr(part, "parsed", None)
            if parsed is not None:
                return parsed.model_dump(mode="json") if hasattr(parsed, "model_dump") else parsed

    raise ValueError("Could not extract parsed output from the OpenAI response.")


def advance_state(state: dict, generated_review: str, selected_inputs: dict[str, Any]) -> dict:
    state["generation_count"] += 1
    state["seo_index"] += 1
    state["focus_index"] += 1
    state["tone_index"] += 1
    state["perspective_index"] += 1
    state["property_location_style_index"] += 1
    state["company_name_counter"] += 1
    state["avoid_words_index"] += 1

    state["recent_reviews"] = push_limited(state["recent_reviews"], generated_review, CACHE_LIMIT)
    state["recent_seo_keywords"] = push_limited(state["recent_seo_keywords"], selected_inputs["seo_keyword"], CACHE_LIMIT)
    state["recent_focus_pairs"] = push_limited(
        state["recent_focus_pairs"],
        [selected_inputs["focus_1"], selected_inputs["focus_2"]],
        CACHE_LIMIT,
    )
    return state


def generate_review_from_state(
    base_dir: Path,
    selected_service: str,
    area: str,
    subarea: str,
    property_type: str,
    number_of_cameras: int | None,
    camera_brand: str,
    review_char_limit: int,
    state: dict[str, Any],
    recent_reviews: list[str] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    if selected_service not in SERVICE_STATE_FILES:
        raise ValueError(
            f"Unsupported service '{selected_service}'. Allowed values: {list(SERVICE_STATE_FILES.keys())}"
        )

    schema_path = base_dir / "schema.py"
    system_path = base_dir / "system.txt"
    user_path = base_dir / "user.txt"
    seo_path = base_dir / "SEO_Keywords.json"
    service_path = base_dir / "Service_Keywords.json"

    ReviewResponse = load_schema(schema_path)

    system_prompt = system_path.read_text(encoding="utf-8").strip()
    user_template = user_path.read_text(encoding="utf-8")

    seo_data = load_json(seo_path)
    service_data = load_json(service_path)

    normalized_state = normalize_state(state)
    selected_inputs = get_next_inputs(selected_service, normalized_state, seo_data, service_data)
    recent_reviews = list(recent_reviews or normalized_state["recent_reviews"])

    use_camera_fields = selected_service == "CCTV Installation"

    prompt_variables = {
        "selected_service": selected_service,
        "area": area or "",
        "subarea": subarea or "",
        "property_type": property_type or "",
        "number_of_cameras": number_of_cameras if (use_camera_fields and number_of_cameras is not None) else "",
        "camera_brand": camera_brand if (use_camera_fields and camera_brand) else "",
        "seo_keyword": selected_inputs["seo_keyword"],
        "focus_1": selected_inputs["focus_1"],
        "focus_2": selected_inputs["focus_2"],
        "tone_rule": selected_inputs["tone_rule"],
        "perspective_rule": selected_inputs["perspective_rule"],
        "review_structure_rule": selected_inputs["review_structure_rule"],
        "property_location_rule": selected_inputs["property_location_rule"],
        "company_name_rule": selected_inputs["company_name_rule"],
        "avoid_words_rule": selected_inputs["avoid_words_rule"],
        "recent_reviews_block": build_recent_reviews_block(recent_reviews),
        "review_char_limit": review_char_limit,
    }

    base_user_prompt = render_prompt(user_template, prompt_variables)
    client = OpenAI(api_key=api_key or load_openai_api_key(base_dir / ".env"))

    best_review = None
    best_similarity = None

    for attempt in range(1, MAX_RETRY + 1):
        user_prompt = base_user_prompt
        if attempt > 1:
            user_prompt += (
                "\n\nExtra instruction:\n"
                "Make this output more different from the recent generated reviews. "
                "Use a different opening and different sentence flow."
            )

        response = client.responses.parse(
            model=MODEL,
            input=[
                {"role": "developer", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=ReviewResponse,
            temperature=TEMPERATURE,
            reasoning=REASONING,
        )

        parsed = extract_parsed_response(response)
        review_text = parsed["response"] if isinstance(parsed, dict) else parsed.response
        similarity = max_similarity_against_history(review_text, recent_reviews)

        if best_review is None or similarity < best_similarity:
            best_review = review_text
            best_similarity = similarity

        if similarity < SIMILARITY_THRESHOLD:
            break

    if best_review is None:
        raise ValueError("Could not generate review.")

    return {
        "review": best_review,
        "selected_inputs": selected_inputs,
        "similarity": best_similarity,
    }


def generate_review(
    base_dir: Path,
    selected_service: str,
    area: str,
    subarea: str,
    property_type: str,
    number_of_cameras: int | None,
    camera_brand: str,
    review_char_limit: int,
    show_prompt_preview: bool,
    show_meta: bool,
) -> None:
    if selected_service not in SERVICE_STATE_FILES:
        raise ValueError(
            f"Unsupported service '{selected_service}'. Allowed values: {list(SERVICE_STATE_FILES.keys())}"
        )

    state_dir = base_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / SERVICE_STATE_FILES[selected_service]

    state = load_state(state_path)
    result = generate_review_from_state(
        base_dir=base_dir,
        selected_service=selected_service,
        area=area,
        subarea=subarea,
        property_type=property_type,
        number_of_cameras=number_of_cameras,
        camera_brand=camera_brand,
        review_char_limit=review_char_limit,
        state=state,
        recent_reviews=state["recent_reviews"],
    )

    final_review = result["review"]
    selected_inputs = result["selected_inputs"]
    best_similarity = result["similarity"]

    state = advance_state(state, final_review, selected_inputs)
    save_state(state_path, state)

    print(final_review)

    if show_meta:
        print("\n--- META ---")
        print(f"State file: {state_path}")
        print(f"SEO keyword used: {selected_inputs['seo_keyword']}")
        print(f"Focus 1 used: {selected_inputs['focus_1']}")
        print(f"Focus 2 used: {selected_inputs['focus_2']}")
        print(f"Tone rule used: {selected_inputs['tone_rule']}")
        print(f"Perspective rule used: {selected_inputs['perspective_rule']}")
        print(f"Review structure rule used: {selected_inputs['review_structure_rule']}")
        print(f"Property and location rule used: {selected_inputs['property_location_rule']}")
        print(f"Company name rule used: {selected_inputs['company_name_rule']}")
        print(f"Avoid words rule used: {selected_inputs['avoid_words_rule']}")
        print(f"Similarity vs recent cache: {best_similarity:.4f}" if best_similarity is not None else "Similarity: N/A")


def parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None

    stripped = value.strip()
    if stripped == "":
        return None

    try:
        return int(stripped)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer or blank value, got {value!r}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate one Nilkanth Infotech review from CLI")

    parser.add_argument("--base-dir", type=str, default=".", help="Base directory containing prompts, schema, JSON files, and state/")
    parser.add_argument("--service", required=True, help="Selected service")
    parser.add_argument("--area", default="", help="Area")
    parser.add_argument("--subarea", default="", help="Subarea")
    parser.add_argument("--property-type", required=True, help="Property type")
    parser.add_argument(
        "--number-of-cameras",
        type=parse_optional_int,
        nargs="?",
        const=None,
        default=None,
        help="Number of cameras",
    )
    parser.add_argument("--camera-brand", nargs="?", const="", default="", help="Camera brand")
    parser.add_argument("--review-char-limit", type=int, default=400, help="Maximum review length")
    parser.add_argument("--show-prompt-preview", action="store_true", help="Print system and user prompts before generation")
    parser.add_argument("--show-meta", action="store_true", help="Print used state/rotation metadata")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    generate_review(
        base_dir=Path(args.base_dir).resolve(),
        selected_service=args.service,
        area=args.area,
        subarea=args.subarea,
        property_type=args.property_type,
        number_of_cameras=args.number_of_cameras,
        camera_brand=args.camera_brand,
        review_char_limit=args.review_char_limit,
        show_prompt_preview=args.show_prompt_preview,
        show_meta=args.show_meta,
    )


if __name__ == "__main__":
    main()
