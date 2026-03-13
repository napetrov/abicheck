import json, sys

data = json.load(open("results/validate_examples.json"))
s = data["summary"]
print("Results:", json.dumps(s))
fails = s.get("FAIL", 0) + s.get("ERROR", 0)
if fails:
    sys.exit(1)
