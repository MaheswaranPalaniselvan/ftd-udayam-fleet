import openpyxl

import re

def clean_int(val) -> int:
    if val is None or val == "":
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    cleaned = str(val).replace(",", "").strip()
    try:
        return int(float(cleaned))
    except ValueError:
        digits = re.sub(r"[^\d]", "", cleaned.split(".")[0])
        return int(digits) if digits else 0

wb = openpyxl.load_workbook('public/udayam_latest.xlsx', data_only=True)
ws = wb['Universe']

districts = []
state_agg = {}

for row in ws.iter_rows(min_row=2, values_only=True):
    level = row[0]
    st_code = row[1].split("-")[0] if row[1] else ""
    code = row[1]
    st_name = row[2]
    loc_name = row[3]
    total = clean_int(row[7])
    last_rec = row[9]
    extracted = clean_int(row[11])
    status = (row[13] or 'Pending').strip()
    claimed_by = row[14]

    if level == 'District':
        pending = max(0, total - extracted)
        districts.append({
            'code': code,
            'state_code': st_code,
            'state_name': st_name,
            'district_name': loc_name,
            'total': total,
            'extracted': extracted,
            'pending': pending,
            'status': status,
            'claimed_by': claimed_by
        })

        if st_code not in state_agg:
            state_agg[st_code] = {'name': st_name, 'total': 0, 'extracted': 0, 'pending': 0, 'completed_districts': 0, 'total_districts': 0}
        state_agg[st_code]['total'] += total
        state_agg[st_code]['extracted'] += extracted
        state_agg[st_code]['pending'] += pending
        state_agg[st_code]['total_districts'] += 1
        if status.lower() == 'completed':
            state_agg[st_code]['completed_districts'] += 1

print(f"Total Districts: {len(districts)}")
completed_d = [d for d in districts if d['status'].lower() == 'completed']
print(f"Completed Districts: {len(completed_d)}")

# States sorted by pending records
states_sorted = sorted(state_agg.items(), key=lambda x: (x[1]['completed_districts'] == x[1]['total_districts'], x[1]['pending']))
print("\n=== STATES RANKED BY LEAST PENDING RECORDS ===")
print(f"{'Code':<6} {'State Name':<30} {'Districts':<12} {'Total':<10} {'Extracted':<10} {'Pending':<10} {'% Done':<8}")
print("-" * 90)
for code, data in states_sorted[:25]:
    pct = (data['extracted'] / data['total'] * 100) if data['total'] > 0 else 0
    dist_ratio = f"{data['completed_districts']}/{data['total_districts']}"
    print(f"{code:<6} {data['name']:<30} {dist_ratio:<12} {data['total']:<10} {data['extracted']:<10} {data['pending']:<10} {pct:<8.1f}%")

truly_pending = [d for d in districts if d['status'].lower() != 'completed' and d['extracted'] < d['total']]
truly_pending.sort(key=lambda d: (d['total'] - d['extracted']))

print(f"\n=== TRULY PENDING DISTRICTS (Extracted < Total), RANKED BY SMALLEST REMAINING ===")
print(f"{'Code':<8} {'State':<20} {'District Name':<25} {'Total':<8} {'Extracted':<10} {'Pending':<10} {'Status':<10}")
print("-" * 95)
for d in truly_pending[:45]:
    p = d['total'] - d['extracted']
    print(f"{d['code']:<8} {d['state_name'][:18]:<20} {d['district_name'][:23]:<25} {d['total']:<8} {d['extracted']:<10} {p:<10} {d['status']:<10}")




