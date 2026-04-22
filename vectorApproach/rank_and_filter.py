import json
import re

def detect_system_category(text, meta):
    category_patterns = [
        ("transmission", r"\b(?:dq200|dsg|mechatronic|gearbox|clutch|kavrama|sanziman|sanzuman)\b"),
        ("oil_lube", r"\b(?:oil consumption|burning oil|oil leak|oil pressure|yag yakma|yag eksiltme|yag kacagi)\b"),
        ("cooling", r"\b(?:coolant|water pump|overheat|radiator|antifreeze|hararet|sogutma)\b"),
        ("turbo_induction", r"\b(?:turbo|wastegate|boost)\b"),
        ("sunroof_water", r"\b(?:sunroof|cam tavan|drain tube|water ingress|headliner)\b"),
        ("electrical", r"\b(?:sensor|battery|alternator|electrical|wiring|module|elektrik|ak\u00fc)\b"),
        ("suspension_steering", r"\b(?:suspension|steering|shock|amortis[o\u00f6]r|direksiyon)\b"),
    ]

    lowered = text or ""
    for name, pattern in category_patterns:
        if re.search(pattern, lowered, re.I):
            return name

    if meta.get("engine_common_names") or meta.get("engine_family"):
        return "engine_general"
    return "general"

def diversify_head(sorted_chunks, head_size=30):
    head = sorted_chunks[:head_size]
    tail = sorted_chunks[head_size:]
    if not head:
        return sorted_chunks

    picked = []
    picked_ids = set()
    seen_categories = set()

    # First pass: ensure category coverage in the head.
    for chunk in head:
        cid = chunk.get("id")
        cat = chunk.get("system_category", "general")
        if cid in picked_ids:
            continue
        if cat != "general" and cat not in seen_categories:
            picked.append(chunk)
            picked_ids.add(cid)
            seen_categories.add(cat)

    # Second pass: keep original quality order for everything else.
    for chunk in head:
        cid = chunk.get("id")
        if cid not in picked_ids:
            picked.append(chunk)
            picked_ids.add(cid)

    # Tail remains in original order.
    return picked + tail

def rank_and_filter(chunks, resolved_spec):
    final_results = []
    
    # Exclusions (The "Step 5" logic)
    # Correctly identify what is WRONG based on the resolved listing
    wrong_timing = "chain" if resolved_spec.get('timing_drive') == "belt" else "belt"
    wrong_fuel = "diesel" if resolved_spec.get('fuel_type') == "petrol" else "petrol"
    
    # Generic model/slug for Tier 4 identification
    # "Clio MK4" -> "clio_mk4"
    current_model_tag = resolved_spec.get('model_name', '').lower().replace(' ', '_')
    
    # Advice penalty patterns (to demote technical solutions/guides)
    advice_patterns = [
        r'\bnasıl (?:yapılır|tamir edilir)\b',
        r'\b(?:how to|step by step|guide|diy|repair|fix)\b',
        r'\b(?:çözümü|çözüm yolu)\b'
    ]
    advice_re = [re.compile(p, re.I) for p in advice_patterns]

    # Neutral Problem Keywords (Signal)
    problem_keywords = [
        r'\b(?:problem|issue|fault|fail|chronic|defect|rattle|leak|broken|unreliable)\b',
        r'\b(?:sorun|arıza|sıkıntı|hata|kaçağı|zırıltı|kronik|bozuk|aksaklık)\b',
        r'\b(?:masraf|maliyet|repair cost)\b'
    ]
    problem_re = [re.compile(p, re.I) for p in problem_keywords]

    # Issue-specific expressions that should count as strong evidence even when
    # generic "problem/issue" words are missing in the same sentence.
    specific_issue_patterns = [
        r'\b(?:oil consumption|burning oil|burn oil|oil leak|oil pressure|coolant leak|water pump leak|yag yakma|yag eksiltme|yag kacagi)\b',
        r'\b(?:dq200|dsg|mechatronic|kavrama|clutch|gearbox|sanziman|sanzuman)\b.{0,45}\b(?:problem|issue|fault|fail|judder|jerk|slip|shock|overheat|rattle|sorun|ariza|titreme|silkeleme|kaydirma)\b',
        r'\b(?:problem|issue|fault|fail|judder|jerk|slip|shock|overheat|rattle|sorun|ariza|titreme|silkeleme|kaydirma)\b.{0,45}\b(?:dq200|dsg|mechatronic|kavrama|clutch|gearbox|sanziman|sanzuman)\b',
        r'\b(?:wastegate|turbo failure|turbocharger failure)\b'
    ]
    specific_issue_re = [re.compile(p, re.I) for p in specific_issue_patterns]

    # Negation Keywords (False Alarms)
    negation_keywords = [
        r'\b(?:hiçbir sıkıntı|sıkıntı yok|sorun yok|sorunsuz|sıkıntısız|masrafsız|no problem|no issue)\b',
        r'\b(?:arıza yok|hata yok)\b'
    ]
    negation_re = [re.compile(p, re.I) for p in negation_keywords]

    # Noise/Vlog Keywords (Penalty)
    noise_keywords = [
        r'\b(?:subscribe|welcome|channel|price|market|dealership|pazar|fiyat|bayi|abone|hoşgeldiniz)\b',
        r'\b(?:0-100|performance|hızlanma|performance|test sürüşü|ride)\b'
    ]
    noise_re = [re.compile(p, re.I) for p in noise_keywords]

    for chunk in chunks:
        meta = chunk['metadata']
        text = chunk['text']
        
        # Hard Exclusions (Step 5)
        if meta.get('is_flagged'): continue # Drop cross-generation risks
        if meta.get('timing_drive') == wrong_timing: continue
        if meta.get('fuel_type') == wrong_fuel: continue
        
        # If chunk is explicitly tagged for a DIFFERENT model (in a shared DB)
        chunk_model = meta.get('model', '').lower()
        if chunk_model and current_model_tag and current_model_tag not in chunk_model:
            continue

        # If a chunk explicitly declares engine/family and it's not the target, exclude it.
        target_engine = resolved_spec.get('engine_common_name')
        target_family = resolved_spec.get('engine_family')
        chunk_family = meta.get('engine_family')
        if target_family and chunk_family and chunk_family != "unknown" and chunk_family != target_family:
            continue

        engine_names_raw = meta.get('engine_common_names', '')
        engine_names = []
        if isinstance(engine_names_raw, str):
            engine_names = [e.strip() for e in engine_names_raw.split(',') if e.strip()]
        elif isinstance(engine_names_raw, (list, tuple)):
            engine_names = [str(e).strip() for e in engine_names_raw if str(e).strip()]

        if target_engine and engine_names and target_engine not in engine_names:
            continue

        target_transmissions = [str(t).lower() for t in (resolved_spec.get('transmissions') or [])]
        chunk_transmission = str(meta.get('transmission') or '').lower()
        has_transmission_match = False
        if chunk_transmission and target_transmissions:
            has_transmission_match = any(t in chunk_transmission for t in target_transmissions)
            if not has_transmission_match and "dsg" in chunk_transmission:
                has_transmission_match = any(t.startswith("dq") for t in target_transmissions)
            
        # Year Proximity Exclusion
        listing_year = resolved_spec.get('listing_year')
        chunk_years = []
        if meta.get('years'):
            chunk_years = [int(y) for y in meta.get('years', '').split(',') if y.strip()]
            
        if listing_year and chunk_years:
            # If all mentioned years are too far (> 5 years) and outside the 2013-2019 window
            # e.g. chunk mentions 2007 but listing is 2016
            if all(abs(y - listing_year) > 6 for y in chunk_years):
                continue

        # Issue Detection Score
        raw_issue_hits = sum(1 for p in problem_re if p.search(text))
        specific_issue_hits = sum(1 for p in specific_issue_re if p.search(text))
        negation_hits = sum(1 for p in negation_re if p.search(text))
        issue_hits = max(0, raw_issue_hits + specific_issue_hits - negation_hits)
        
        noise_hits = sum(1 for p in noise_re if p.search(text))
        
        # Assign Tiers (Step 4)
        tier = 5 # Default low rank
        
        # Tier 4: General Model Match
        if chunk_model and current_model_tag in chunk_model:
            tier = 4

        # Feature Match (Sunroof)
        if resolved_spec.get('has_sunroof') and meta.get('has_sunroof'):
            tier = min(tier, 2) # Start at Tier 2 for relevant features
            
        # Tier 3: Mileage Match
        onset_km = meta.get('onset_km')
        if onset_km and abs(onset_km - resolved_spec.get('listing_km', 0)) <= 20000:
            tier = min(tier, 3)
            
        # Tier 2: Family Match
        if meta.get('engine_family') == resolved_spec.get('engine_family'):
            tier = min(tier, 2)
            
        # Tier 1: Exact Match
        if resolved_spec.get('engine_common_name') in engine_names:
            years_raw = meta.get('years', '')
            years = []
            if isinstance(years_raw, str) and years_raw:
                years = [int(y) for y in years_raw.split(',') if y.strip()]
            elif isinstance(years_raw, (list, tuple)):
                years = list(years_raw)
                
            if resolved_spec.get('listing_year') in years:
                tier = min(tier, 1)
            elif not years: 
                tier = min(tier, 2)
        
        # Power Match Logic
        power_raw = meta.get('power_hp', '')
        powers = []
        if isinstance(power_raw, str) and power_raw:
            powers = [int(p) for p in power_raw.split(',') if p.strip()]
        
        has_power_match = False
        has_power_mismatch = False
        if resolved_spec.get('listing_power_hp') and powers:
            if resolved_spec['listing_power_hp'] in powers:
                has_power_match = True
            else:
                has_power_mismatch = True

        # Tier 0: Perfect Match (Engine + Year + Power)
        if tier == 1 and (has_power_match or resolved_spec.get('listing_power_hp') is None):
            # If power is not in listing, we don't penalize for lack of it
            tier = 0
            
        # Penalty: Explicit Power Mismatch
        if has_power_mismatch:
            tier = max(tier, 4) 

        # FINAL ADJUSTMENT: Issue Signal
        if issue_hits > 0:
            tier = max(0, tier - 2) # Strong boost for problems
        if specific_issue_hits > 0:
            tier = max(0, tier - 1)

        # If the chunk matches the listing transmission and carries an issue signal,
        # keep it visible instead of burying it under generic vlog penalties.
        if has_transmission_match and issue_hits > 0:
            tier = min(tier, 3)
            if specific_issue_hits > 0:
                tier = min(tier, 2)
            
        # Penalize if it explicitly contains negations (false alarms)
        if negation_hits > 0:
            tier = min(5, tier + 2)

        if noise_hits > issue_hits and specific_issue_hits == 0:
            tier = min(5, tier + 2) # Strong penalty for vlog fluff

        # Advice Check (No Technical Solution Advice Rule)
        chunk['contains_advice'] = any(p.search(text) for p in advice_re)
        if chunk['contains_advice']:
            advice_penalty = 1 if specific_issue_hits > 0 else 2
            tier = min(tier + advice_penalty, 5)

        # Re-apply transmission visibility after penalties so DQ/DSG issues do
        # not disappear purely due to guide-like wording.
        if has_transmission_match and issue_hits > 0:
            tier = min(tier, 3)
            if specific_issue_hits > 0:
                tier = min(tier, 2)

        chunk['system_category'] = detect_system_category(text, meta)
        chunk['tier'] = tier
        chunk['issue_signal'] = issue_hits
        final_results.append(chunk)
        
    # Sort by Tier (Lower number is better), then by Issue Signal (Higher is better), then by Distance
    final_results.sort(key=lambda x: (x['tier'], -x['issue_signal'], x['distance']))

    # Improve top-of-list coverage by avoiding single-category domination.
    return diversify_head(final_results, head_size=30)

if __name__ == "__main__":
    with open('outputs/retrieved_chunks.json', 'r', encoding='utf-8') as f:
        retrieved = json.load(f)
        
    with open('outputs/resolved_spec.json', 'r') as f:
        spec = json.load(f)
        
    final_ranked = rank_and_filter(retrieved, spec)
    
    # print(f"Final results after ranking and filtering: {len(final_ranked)} chunks.")
    # for c in final_ranked:
    #     print(f"Tier {c['tier']} | ID: {c['id']} | {c['text'][:80]}...")
        
    with open('outputs/final_output.json', 'w', encoding='utf-8') as f:
        json.dump(final_ranked, f, indent=2, ensure_ascii=False)
