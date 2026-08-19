from ddgs import DDGS
import json

try:
    with DDGS() as ddgs:
        results = list(ddgs.text("technology news", max_results=5))
        print(json.dumps(results, indent=2))
except Exception as e:
    print(f"Error: {e}")
