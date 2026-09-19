from app.trust.mouser_client import search_component


def build_component_profile(part_number: str):
    results = search_component(part_number)

    if not results:
        raise ValueError(f"No component found for {part_number}")

    target = part_number.strip().lower()

    # Prefer exact manufacturer part-number match
    exact_matches = [
        part for part in results
        if part.get("ManufacturerPartNumber", "").strip().lower() == target
    ]

    part = exact_matches[0] if exact_matches else results[0]

    return {
        "requested_part": part_number,
        "matched_mpn": part.get("ManufacturerPartNumber"),
        "manufacturer": part.get("Manufacturer"),
        "description": part.get("Description"),
        "category": part.get("Category"),
        "datasheet_url": part.get("DataSheetUrl"),
        "product_detail_url": part.get("ProductDetailUrl")
    }