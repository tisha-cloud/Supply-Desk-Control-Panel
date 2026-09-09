from requirement_engine import RequirementEngine
from ppt_generator import PPTGenerator

re = RequirementEngine()
matches = re.match_requirements(query="Outer Ring Road managed office space", top_n=5)
summary = re.generate_summary(matches)

print(f"Matched {len(matches)} options for query 'Outer Ring Road managed office space':")
for idx, m in enumerate(matches, 1):
    print(f"  {idx}. {m.get('building_name', m.get('property_name'))} | {m.get('developer_landlord', m.get('developer_name'))} | Area: {m.get('available_inventory_sqft')} | Rent: {m.get('quoted_rental_sqft_pm')}")

generator = PPTGenerator()
out_path = generator.generate_presentation(
    matched_records=matches,
    summary_data=summary,
    client_name="Corporate Client",
    requirement_summary="ORR Office Search",
    output_filename="ORR_Office_Options_Deck.pptx"
)

print(f"Successfully generated deck at: {out_path}")
