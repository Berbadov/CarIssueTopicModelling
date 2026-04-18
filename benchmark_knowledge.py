import json
import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime

# Static ground truth definitions
# Each key represents a car model. Each value is a list of known chronic issues.
# Each issue has a name and a list of regex patterns to match against extracted knowledge fields.
GROUND_TRUTH = {
    "renault_clio_mk4": [
        {
            "id": "clio_oil_consumption",
            "name": "Excessive Oil Consumption / Timing Chain (1.2 TCe)",
            "patterns": [r"oil\s+consumption", r"timing\s+chain", r"1\.2\s+tce", r"loss\s+of\s+oil"]
        },
        {
            "id": "clio_edc_gearbox",
            "name": "EDC Gearbox / TCU Failure / Jerky Shifting",
            "patterns": [r"edc", r"gearbox", r"tcu", r"transmission", r"jerky", r"clutch actuator", r"loss of even gears"]
        },
        {
            "id": "clio_rlink_infotainment",
            "name": "R-Link Infotainment Glitches / Freezing",
            "patterns": [r"r-link", r"rlink", r"infotainment", r"screen freeze", r"radio"]
        },
        {
            "id": "clio_suspension_noise",
            "name": "Front Suspension / Anti-Roll Bar Knocking",
            "patterns": [r"suspension", r"knocking", r"anti-roll", r"drop link", r"rattling over bumps", r"creak"]
        },
        {
            "id": "clio_09_ignition_coil",
            "name": "Ignition Coil Failure / Misfire (0.9 TCe)",
            "patterns": [r"ignition\s+coil", r"misfire", r"rough\s+idl", r"0\.9\s+tce"]
        },
        {
            "id": "clio_wind_noise",
            "name": "Wind Noise / Door Seals",
            "patterns": [r"wind\s+noise", r"door\s+seal", r"a-pillar", r"whistling"]
        },
        {
            "id": "clio_key_card",
            "name": "Key Card Recognition Failure",
            "patterns": [r"key\s*card", r"keyless", r"not\s+recognized"]
        }
    ],
    "vw_golf_mk7": [
        {
            "id": "golf_water_pump",
            "name": "Water Pump & Thermostat Housing Leaks",
            "patterns": [r"water\s+pump", r"thermostat", r"coolant\s+leak", r"housing crack", r"sweet\s+smell"]
        },
        {
            "id": "golf_panoramic_sunroof",
            "name": "Panoramic Sunroof Leaks & Creaks",
            "patterns": [r"sunroof", r"panoramic", r"water\s+ingress", r"drain\s+tube", r"headliner leak", r"creak"]
        },
        {
            "id": "golf_dsg_transmission",
            "name": "DSG Transmission / Mechatronics Failure",
            "patterns": [r"dsg", r"mechatronic", r"dq200", r"dq250", r"jerky\s+shift", r"clutch\s+wear"]
        },
        {
            "id": "golf_infotainment_screen",
            "name": "Infotainment 'Ghost Touching' / Screen Defect",
            "patterns": [r"ghost\s+touch", r"infotainment", r"screen\s+defect", r"mib2", r"unresponsive\s+screen"]
        },
        {
            "id": "golf_turbo_failure",
            "name": "Turbocharger Failure (Early 2015 IHI)",
            "patterns": [r"turbo", r"turbocharger", r"ihi", r"shaft failure"]
        },
        {
            "id": "golf_carbon_buildup",
            "name": "Carbon Buildup on Intake Valves",
            "patterns": [r"carbon\s+buildup", r"intake\s+valve", r"walnut\s+blast"]
        },
        {
            "id": "golf_rear_speaker_leak",
            "name": "Rear Door Speaker Water Leaks",
            "patterns": [r"speaker\s+leak", r"door\s+seal\s+leak", r"water\s+in\s+footwell"]
        }
    ]
}

# Mapping dataset files to the specific car model ground truth
DATASETS = [
    {
        "file": "data/processed/issue_knowledge_clio.json",
        "model": "renault_clio_mk4"
    },
    {
        "file": "data/processed/issue_knowledge_youtube_renault_clio_mk4_final.json",
        "model": "renault_clio_mk4"
    },
    {
        "file": "data/processed/issue_knowledge_youtube_vw_golf_mk7_final.json",
        "model": "vw_golf_mk7"
    }
]

HISTORY_FILE = Path("data/benchmarks/benchmark_history.json")

def check_match(text, patterns):
    if not text:
        return False
    text = str(text).lower()
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    return False


def infer_trim_from_title(title):
    text = (title or "").strip()
    if not text:
        return "unknown"
    low = text.lower()
    if re.search(r"\bgtd\b", low):
        return "GTD"
    if re.search(r"\br[- ]?line\b", low):
        return "R-Line"
    if re.search(r"\bgti\b", low) and not re.search(r"\bgtd\b", low):
        return "GTI"
    if re.search(r"\bgolf\s*r\b", low) or re.search(r"\bmk7(?:\.5)?\s*r\b", low):
        return "R"
    if re.search(r"\btdi\b|\bdiesel\b", low):
        return "TDI"
    return "base"


def compute_trim_stats(data):
    trim_distribution = defaultdict(int)
    trim_scope_warning_count = 0
    mono_trim_issues = 0

    for topic in data:
        if topic.get("trim_scope_warning"):
            trim_scope_warning_count += 1

        trim_ev = topic.get("trim_evidence")
        if isinstance(trim_ev, dict) and trim_ev:
            clean = {
                str(k): int(v)
                for k, v in trim_ev.items()
                if isinstance(v, int) and v > 0
            }
        else:
            clean = {}
            for src in topic.get("source_videos", []):
                if not isinstance(src, dict):
                    continue
                trim = str(src.get("trim") or "").strip() or infer_trim_from_title(src.get("title"))
                clean[trim] = clean.get(trim, 0) + 1

        if len(clean) == 1:
            mono_trim_issues += 1
        for trim, count in clean.items():
            trim_distribution[trim] += count

    total_trim_mentions = sum(trim_distribution.values())
    ordered_distribution = dict(
        sorted(trim_distribution.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    mono_trim_issue_pct = (mono_trim_issues / len(data) * 100.0) if data else 0.0

    return {
        "trim_distribution": ordered_distribution,
        "trim_scope_warning_count": trim_scope_warning_count,
        "mono_trim_issue_pct": round(mono_trim_issue_pct, 1),
        "total_trim_mentions": total_trim_mentions,
    }

def evaluate_dataset(file_path, model_key):
    path = Path(file_path)
    if not path.exists():
        print(f"Skipping {file_path} - File not found.")
        return None

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"Error reading JSON from {file_path}")
            return None

    issues = GROUND_TRUTH.get(model_key, [])
    if not issues:
        print(f"No ground truth defined for model key {model_key}")
        return None

    found_issues = set()
    mapped_topics = 0
    total_topics = len(data)

    for topic in data:
        # Combine text fields from the topic
        text_content = " ".join(filter(None, [
            topic.get("label", ""),
            topic.get("label_short", ""),
            topic.get("summary", ""),
            " ".join(topic.get("warning_signs", [])),
            topic.get("notes", "")
        ]))

        topic_matched_any = False
        for issue in issues:
            if check_match(text_content, issue["patterns"]):
                found_issues.add(issue["id"])
                topic_matched_any = True
        
        if topic_matched_any:
            mapped_topics += 1

    recall = len(found_issues) / len(issues) if issues else 0
    precision = mapped_topics / total_topics if total_topics else 0
    trim_stats = compute_trim_stats(data)

    missing_issues = [iss["name"] for iss in issues if iss["id"] not in found_issues]

    print(f"\n--- Benchmark Results for {path.name} ({model_key}) ---")
    print(f"Total Topics Analysed: {total_topics}")
    print(f"Ground Truth Recall: {len(found_issues)} / {len(issues)} ({(recall * 100):.1f}%)")
    print(f"Topic Mapping Precision: {mapped_topics} / {total_topics} ({(precision * 100):.1f}%)")
    print(
        "Trim Scope Warnings: "
        f"{trim_stats['trim_scope_warning_count']} | "
        f"Mono-trim Issue %: {trim_stats['mono_trim_issue_pct']:.1f}%"
    )
    if trim_stats["trim_distribution"]:
        print("Trim Distribution (source evidence):")
        for trim, count in trim_stats["trim_distribution"].items():
            share = (
                count / trim_stats["total_trim_mentions"] * 100.0
                if trim_stats["total_trim_mentions"]
                else 0.0
            )
            print(f"  - {trim}: {count} ({share:.1f}%)")
    print("")
    
    if missing_issues:
        print("\nMissing Ground Truth Issues:")
        for mi in missing_issues:
            print(f"  - {mi}")
    else:
        print("\nAll Ground Truth Issues were successfully detected!")

    return {
        "dataset": path.name,
        "total_topics": total_topics,
        "recall_pct": round(recall * 100, 1),
        "precision_pct": round(precision * 100, 1),
        "found_count": len(found_issues),
        "total_gt": len(issues),
        "missing": missing_issues,
        "trim_stats": {
            "trim_distribution": trim_stats["trim_distribution"],
            "trim_scope_warning_count": trim_stats["trim_scope_warning_count"],
            "mono_trim_issue_pct": trim_stats["mono_trim_issue_pct"],
        },
    }

def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_history(history):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

def main():
    print("Starting Static Knowledge Extraction Benchmark...")
    history = load_history()
    
    current_run = {
        "timestamp": datetime.now().isoformat(),
        "results": {}
    }

    for ds in DATASETS:
        res = evaluate_dataset(ds["file"], ds["model"])
        if res:
            current_run["results"][res["dataset"]] = res

    history.append(current_run)
    save_history(history)

    # Print Brief Comparison
    print("\n" + "="*75)
    print("QUICK COMPARISON (Current vs Previous Run)")
    print("="*75)
    
    if len(history) < 2:
        print("This is the first run. No previous data to compare against.")
    else:
        prev_run = history[-2]["results"]
        curr_run = current_run["results"]
        
        print(f"{'Dataset':<40} | {'Recall':<14} | {'Precision':<14}")
        print("-" * 75)
        
        for ds_name, curr_data in curr_run.items():
            prev_data = prev_run.get(ds_name)
            
            curr_rec = f"{curr_data['recall_pct']}%"
            curr_prec = f"{curr_data['precision_pct']}%"
            
            if prev_data:
                rec_diff = curr_data['recall_pct'] - prev_data['recall_pct']
                prec_diff = curr_data['precision_pct'] - prev_data['precision_pct']
                
                # Format with explicitly + or -
                rec_str = f"{curr_rec} ({rec_diff:+.1f}%)" if rec_diff != 0 else f"{curr_rec} (-)"
                prec_str = f"{curr_prec} ({prec_diff:+.1f}%)" if prec_diff != 0 else f"{curr_prec} (-)"
            else:
                rec_str = f"{curr_rec} (new)"
                prec_str = f"{curr_prec} (new)"
                
            print(f"{ds_name:<40} | {rec_str:<14} | {prec_str:<14}")
    print("="*75)

if __name__ == "__main__":
    main()
