"""
Standalone PPT Builder — Uses the updated PPTGenerator with the new clean database.
Can be run directly: python build_full_ppt.py "Show me ORR options"
"""
import os
import sys
import argparse

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from requirement_engine import RequirementEngine
from ppt_generator import PPTGenerator
from ai_client import AIClient


def build_deck(query=None, micromarket=None, fitout=None, developer=None,
               min_area=None, max_area=None, min_rent=None, max_rent=None,
               client_name="Valued Client", top_n=10, template_name="options format.pptx"):
    """
    End-to-end deck builder:
    1. Load database (centralized_database.csv)
    2. Filter/match properties based on user criteria
    3. Generate PowerPoint presentation from template
    """
    print("=" * 60)
    print("COMMERCIAL REAL ESTATE PITCH DECK GENERATOR")
    print("=" * 60)
    
    # 1. Load database
    engine = RequirementEngine()
    print(f"Database loaded: {len(engine.df)} property listings")
    
    # 2. Try AI-powered query parsing if we have a natural language query
    search_params = {}
    if query:
        ai = AIClient()
        if ai.get_active_provider() != "none":
            print(f"Parsing query with {ai.get_active_provider().upper()} AI...")
            parsed = ai.parse_natural_language_query(query)
            search_params.update({k: v for k, v in parsed.items() if v is not None})
            print(f"  Parsed: {search_params}")
        search_params.setdefault('query', query)
    
    # Override with explicit params
    if micromarket: search_params['micromarket'] = micromarket
    if fitout: search_params['fitout'] = fitout
    if developer: search_params['developer'] = developer
    if min_area: search_params['min_area'] = float(min_area)
    if max_area: search_params['max_area'] = float(max_area)
    if min_rent: search_params['min_rent'] = float(min_rent)
    if max_rent: search_params['max_rent'] = float(max_rent)
    
    # 3. Match
    results = engine.match_requirements(
        query=search_params.get('query'),
        micromarket=search_params.get('micromarket'),
        min_area=search_params.get('min_area'),
        max_area=search_params.get('max_area'),
        min_rent=search_params.get('min_rent'),
        max_rent=search_params.get('max_rent'),
        fitout=search_params.get('fitout'),
        developer=search_params.get('developer'),
        top_n=top_n
    )
    
    if not results:
        print("[WARN] No properties matched. Generating deck with all top listings...")
        results = engine.match_requirements(top_n=top_n)
    
    print(f"Matched {len(results)} properties:")
    for i, r in enumerate(results[:5], 1):
        bname = r.get('building_name', '?')
        dev = r.get('developer_landlord', r.get('developer_name', '?'))
        mm = r.get('micromarket_category', '?')
        area = r.get('available_inventory_sqft', '?')
        print(f"  {i}. {bname} | {dev} | {mm} | Area: {area}")
    if len(results) > 5:
        print(f"  ... and {len(results) - 5} more")
    
    # 4. Generate summary
    summary = engine.generate_summary(results)
    
    # 5. Build PPT
    print(f"\nGenerating presentation deck...")
    gen = PPTGenerator(template_name=template_name)
    
    clean_name = (client_name or "Client").replace(" ", "_")
    filename = f"Commercial_Pitch_Deck_{clean_name}.pptx"
    
    output_path = gen.generate_presentation(
        matched_records=results,
        summary_data=summary,
        client_name=client_name,
        requirement_summary=query or "Office Space Options",
        output_filename=filename
    )
    
    print(f"\n{'=' * 60}")
    print(f"DECK GENERATED SUCCESSFULLY")
    print(f"{'=' * 60}")
    print(f"Options Included  : {len(results)}")
    print(f"Total Area        : {summary.get('total_area', 0):,} Sq. Ft.")
    print(f"Avg Rent          : INR {summary.get('avg_rent', 0):,.2f} / Sq. Ft. / Month")
    print(f"Micromarkets      : {', '.join(summary.get('micromarkets_covered', []))}")
    print(f"Output File       : {output_path}")
    print(f"{'=' * 60}")
    
    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Build a commercial real estate pitch deck")
    parser.add_argument("query", nargs="?", default=None, help="Natural language search query")
    parser.add_argument("--micromarket", "-m", default=None, help="Filter by micromarket (e.g. ORR, CBD, WF)")
    parser.add_argument("--fitout", "-f", default=None, help="Filter by fitout type")
    parser.add_argument("--developer", "-d", default=None, help="Filter by developer name")
    parser.add_argument("--min-area", type=float, default=None, help="Minimum area in sq ft")
    parser.add_argument("--max-area", type=float, default=None, help="Maximum area in sq ft")
    parser.add_argument("--min-rent", type=float, default=None, help="Minimum rent per sq ft per month")
    parser.add_argument("--max-rent", type=float, default=None, help="Maximum rent per sq ft per month")
    parser.add_argument("--client", "-c", default="Valued Client", help="Client name for the deck")
    parser.add_argument("--top-n", "-n", type=int, default=10, help="Maximum number of options to include")
    parser.add_argument("--template", "-t", default="options format.pptx", help="Template filename")
    args = parser.parse_args()
    
    build_deck(
        query=args.query,
        micromarket=args.micromarket,
        fitout=args.fitout,
        developer=args.developer,
        min_area=args.min_area,
        max_area=args.max_area,
        min_rent=args.min_rent,
        max_rent=args.max_rent,
        client_name=args.client,
        top_n=args.top_n,
        template_name=args.template
    )
