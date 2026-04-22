import json

with open('vectorApproach/outputs/final_output.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

issues = [c for c in data if c['issue_signal'] > 0]
for idx, c in enumerate(issues[:5], 1):
    print(f"[{idx}] (Signal: {c['issue_signal']} | Tier: {c['tier']})")
    print(c['text'].replace('passage: ', ''))
    print("-" * 50)
