import os
import subprocess
import yaml
import glob
import time

scaffolds = []
for f in glob.glob('data/scaffolds/*.yaml'):
    # Skip reference or existing models to avoid redundant runs
    if any(k in f for k in ['mk7', 'mk4', 'renault_clio.yaml', 'vw_golf.yaml']):
        continue
    with open(f) as r:
        try:
            data = yaml.safe_load(r)
            meta = data.get('meta', {})
            model = meta.get('model')
            if model:
                slug = os.path.basename(f).replace(".yaml", "")
                scaffolds.append((slug, model))
        except:
            continue

print(f"Found {len(scaffolds)} models to process: {[s[1] for s in scaffolds]}")

for slug, model in scaffolds:
    print(f"\n" + "="*80)
    print(f" PROCESSING: {model} ({slug})")
    print("="*80)
    
    cmd = [
        "python", "scripts/run_pipeline.py",
        "--car", model,
        "--slug", slug,
        "--max-videos", "15",
        "--min-views", "30000",
        "--force"
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print(f"SUCCESS: {model}")
    except subprocess.CalledProcessError as e:
        print(f"FAILED: {model} (exit {e.returncode})")
    
    # Small pause between models to mitigate rate limits
    time.sleep(2)

print("\nAll models processed.")
