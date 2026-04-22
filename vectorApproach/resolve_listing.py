import yaml
import re
import json
import argparse
from pathlib import Path

def load_scaffold(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def extract_basic_info(text):
    # Try labeled "Year: 2016" first
    year_label = re.search(r'Year:\s*(\d{4})', text, re.I)
    if year_label:
        year = int(year_label.group(1))
    else:
        # Fallback to any 4-digit number (but avoid the current date)
        years = re.findall(r'\b(19\d{2}|20\d{2})\b', text)
        # Assuming the smallest year is likely the production year in a listing
        year = min([int(y) for y in years]) if years else None
    
    # Power Extraction: e.g., "Engine Power: 125 hp"
    power_match = re.search(r'(?:Engine Power|Beygir Gücü|Güç)\s*[:=-]?\s*(\d+)\s*(?:hp|ps|bg|beygir)', text, re.I)
    power = int(power_match.group(1)) if power_match else None

    # KM: Look for "KM: 79.000" or "79000 km"
    km_match = re.search(r'(?:KM|Kilometre|Kilometers)\s*[:=-]?\s*(\d{1,3}(?:[.,\s]\d{3})*|\d{4,7})', text, re.I)
    km = None
    if km_match:
        km_str = km_match.group(1).replace('.', '').replace(',', '').replace(' ', '')
        km = int(km_str)
        
    return year, km, power

def resolve_variant(listing_text, scaffold, model_name="Vehicle"):
    listing_year, listing_km, listing_power = extract_basic_info(listing_text)
    print(f"DEBUG: Parsed Year: {listing_year}, KM: {listing_km}, Power: {listing_power}")
    
    # Detect Sunroof
    has_sunroof = bool(re.search(r'\b(sunroof|cam tavan|panoramik|panoramic|glass roof|highline|icon)\b', listing_text, re.I))
    
    resolved = {
        "model_name": model_name,
        "listing_year": listing_year,
        "listing_km": listing_km,
        "listing_power_hp": listing_power,
        "has_sunroof": has_sunroof,
        "engine_common_name": None,
        "fuel_type": None,
        "timing_drive": None,
        "engine_family": None,
        "transmissions": [],
        "facelift_status": "pre-facelift"
    }

    # Match Engine by Common Name/Search Alias
    found_engine = False
    for family in scaffold.get('engine_families', []):
        for disp in family.get('displacements', []):
            aliases = disp.get('search_alias', [])
            code = disp.get('code', '')
            
            # Clean up the code for matching (replace _ with space)
            clean_code = code.replace('_', ' ')
            
            for alias in [code, clean_code] + aliases:
                if not alias: continue
                # Tolerant regex
                pattern = re.escape(alias).replace(r'\ ', r'[\s-]*').replace(r'\.', r'[.,]?').replace(r'_', r'[\s-]*')
                if re.search(rf'\b{pattern}\b', listing_text, re.I):
                    yr = disp.get('year_range', [0, 9999])
                    if listing_year and (listing_year < yr[0] or listing_year > yr[1]):
                        print(f"DEBUG: Match found for {alias} but year {listing_year} out of range {yr}")
                        continue
                    
                    resolved["engine_common_name"] = code
                    resolved["engine_family"] = family.get('code')
                    resolved["fuel_type"] = family.get('fuel_type')
                    resolved["timing_drive"] = family.get('timing_drive')
                    found_engine = True
                    print(f"DEBUG: Successfully matched engine: {code}")
                    break
            if found_engine: break
        if found_engine: break

    if not found_engine:
        return None, "Could not match engine within valid year range."

    # Resolve Facelift Status
    for fl in scaffold.get('facelifts', []):
        if listing_year and listing_year >= fl.get('year'):
            resolved["facelift_status"] = "post-facelift"
            break

    # Resolve Compatible Transmissions
    # If listing says "Automatic" or "Manual", we filter the scaffold list
    is_auto = bool(re.search(r'\b(automatic|otomatik|dsg|edc)\b', listing_text, re.I))
    
    for trans in scaffold.get('transmissions', []):
        # Check compatibility with engine
        if resolved["engine_common_name"] in trans.get('compatible_displacements', []):
            # Check year range
            tr_yr = trans.get('year_range', [0, 9999])
            if listing_year and (listing_year >= tr_yr[0] and listing_year <= tr_yr[1]):
                # If we know it's auto, only include auto types
                t_type = trans.get('type', '').lower()
                if is_auto:
                    if 'manual' not in t_type:
                        resolved["transmissions"].append(trans['code'])
                else:
                    resolved["transmissions"].append(trans['code'])

    return resolved, None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scaffold", default="scaffolds/renault_clio_mk4.yaml")
    parser.add_argument("--listing", default="data_raw/listing_clio_1.5_dci_icon_2016.txt")
    args = parser.parse_args()
    
    with open(args.listing, 'r', encoding='utf-8') as f:
        raw_listing = f.read()
        
    scaffold_data = load_scaffold(args.scaffold)
    m_name = scaffold_data.get('meta', {}).get('model', 'Vehicle')
    
    res, err = resolve_variant(raw_listing, scaffold_data, model_name=m_name)
    
    if err:
        print(f"Error: {err}")
    else:
        print(json.dumps(res, indent=2))
        with open('outputs/resolved_spec.json', 'w') as f:
            json.dump(res, f, indent=2)
