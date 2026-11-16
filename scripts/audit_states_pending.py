import json

with open("client/core/districts_universe.json", encoding="utf-8") as f:
    dists = json.load(f)

states = {}
for d in dists:
    st_code = d["state_code"]
    if st_code not in states:
        states[st_code] = {
            "name": d["state_name"],
            "pending": 0,
            "dists_with_pending": 0,
            "total_dists": 0,
            "total_universe": 0,
            "total_extracted": 0
        }
    s = states[st_code]
    s["total_dists"] += 1
    s["total_universe"] += d["total"]
    s["total_extracted"] += d["extracted"]
    if d["pending"] > 0:
        s["pending"] += d["pending"]
        s["dists_with_pending"] += 1

sorted_states = sorted(states.items(), key=lambda x: (x[1]["pending"] == 0, x[1]["pending"]))

print(f"{'Code':<6} {'State Name':<28} {'Pending Recs':<14} {'Pending Dists':<15} {'Total Univ':<12} {'Total Ext':<12}")
print("-" * 90)
for code, data in sorted_states:
    dist_str = f"{data['dists_with_pending']}/{data['total_dists']} dists"
    print(f"{code:<6} {data['name']:<28} {data['pending']:<14,d} {dist_str:<15} {data['total_universe']:<12,d} {data['total_extracted']:<12,d}")
