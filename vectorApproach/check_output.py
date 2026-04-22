import json

with open('vectorApproach/outputs/final_output.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

issues = [c for c in data if c['issue_signal'] > 0]
print(f"Total chunks: {len(data)}")
print(f"Chunks with issue_signal > 0: {len(issues)}")

for c in data[:15]:
    print(f"Tier: {c['tier']} | Signal: {c['issue_signal']} | Text: {c['text'][:100]}...")
