import os
import re
import openpyxl
from pathlib import Path
from datetime import datetime

def parse_num(val):
    if val is None or val == '':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(',', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

def analyze():
    wb = openpyxl.load_workbook('public/udayam_latest.xlsx', data_only=True)
    ws = wb.active
    
    total_official_msme = 0
    total_districts = 0
    completed_districts = 0
    remaining_districts = 0
    already_extracted_records = 0
    remaining_msme_estimate = 0
    
    state_breakdown = {}

    # Pass 1: populate state metadata
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        level = str(row[0]).strip().lower()
        if level == 'state':
            st_code = str(row[1]).strip()
            st_name = str(row[2]).strip()
            total_msme = parse_num(row[7])
            total_official_msme += total_msme
            state_breakdown[st_code] = {
                'name': st_name,
                'total_msme': total_msme,
                'districts': 0,
                'completed': 0,
                'extracted': 0
            }

    # Pass 2: populate district metadata
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        level = str(row[0]).strip().lower()
        if level == 'district':
            dist_code = str(row[1]).strip()
            st_code = dist_code.split('-')[0] if '-' in dist_code else ''
            dist_name = str(row[3]).strip()
            msme_count = parse_num(row[7])
            extracted = parse_num(row[11])
            status = str(row[13] or '').strip().lower()
            
            total_districts += 1
            if st_code not in state_breakdown:
                state_breakdown[st_code] = {
                    'name': str(row[2]).strip(),
                    'total_msme': 0,
                    'districts': 0,
                    'completed': 0,
                    'extracted': 0
                }
                
            state_breakdown[st_code]['districts'] += 1
            
            if 'completed' in status or extracted > 0:
                completed_districts += 1
                already_extracted_records += extracted
                state_breakdown[st_code]['completed'] += 1
                state_breakdown[st_code]['extracted'] += extracted
            else:
                remaining_districts += 1
                remaining_msme_estimate += msme_count

    print("==================================================================")
    print("📊 ALL-INDIA UDYAM FLEET STATUS & RECORD COUNTS")
    print("==================================================================")
    print(f"Total States / UTs:          {len(state_breakdown)}")
    print(f"Total Districts:             {total_districts}")
    print(f"Completed Districts:         {completed_districts} ({(completed_districts/total_districts)*100:.1f}%)")
    print(f"Remaining Districts:         {remaining_districts} ({(remaining_districts/total_districts)*100:.1f}%)")
    print(f"Official Total MSMEs:        {int(total_official_msme):,} records")
    print(f"Already Harvested:           {int(already_extracted_records):,} records")
    print(f"Remaining Estimated MSMEs:   {int(total_official_msme - already_extracted_records):,} records")
    print("------------------------------------------------------------------")

    # 2. Analyze Historical Log Files
    log_files = list(Path('.').glob('*.log')) + list(Path('logs').glob('*.log'))
    print(f"\nAnalyzing {len(log_files)} historical extraction log files...")
    
    total_log_records = 0
    sample_speeds = []
    
    for lf in log_files:
        if lf.stat().st_size < 10000:
            continue
        try:
            with open(lf, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                
            first_ts = None
            last_ts = None
            records_in_log = 0
            
            for line in lines:
                if ' OK (' in line or ' FAIL ' in line or 'Extracted:' in line or 'Status Recorded:' in line:
                    records_in_log += 1
                    m = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                    if m:
                        ts = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
                        if not first_ts:
                            first_ts = ts
                        last_ts = ts
                        
                m_spd = re.search(r'speed_rpm[\'":\s]+([0-9\.]+)', line)
                if m_spd:
                    val = float(m_spd.group(1))
                    if 5.0 <= val <= 150.0:
                        sample_speeds.append(val)
                    
            if first_ts and last_ts and records_in_log > 100:
                duration_min = (last_ts - first_ts).total_seconds() / 60.0
                if duration_min > 5:
                    rpm = records_in_log / duration_min
                    print(f"  - {lf.name:<32}: {records_in_log:,} records in {duration_min/60:.1f} hrs -> {rpm:.1f} RPM")
                    total_log_records += records_in_log
                    if 5.0 <= rpm <= 150.0:
                        sample_speeds.append(rpm)
        except Exception as e:
            pass
            
    avg_hist_rpm = sum(sample_speeds) / len(sample_speeds) if sample_speeds else 22.0
    print(f"\nHistorical Average Observed Scraping Speed: ~{avg_hist_rpm:.1f} RPM")

    remaining_records = max(1, int(total_official_msme - already_extracted_records))

    print("\n==================================================================")
    print("⏱️ COMPLETION TIME PROJECTIONS FOR ALL STATE RECORDS")
    print("==================================================================")
    
    scenarios = [
        ("1 Machine @ Historical Speed (~22 rpm)", 22),
        ("1 Machine @ New Optimized Engine (~60 rpm)", 60),
        ("2 SBC Workers (e.g. 2 x Pi 5 @ 60 rpm = 120 rpm)", 120),
        ("4 Distributed Fleet Workers (e.g. 2 Pi 5 + 2 PCs = 240 rpm)", 240),
        ("8 Distributed Nodes (~480 rpm)", 480),
        ("16 Distributed Nodes / Cloud Fleet (~960 rpm)", 960),
        ("32 Distributed Fleet Cluster (~1,920 rpm)", 1920)
    ]

    print(f"{'Fleet Architecture':<55} | {'Records/Day':<14} | {'Est. Completion Time'}")
    print(f"{'-'*55}-+-{'-'*14}-+-{'-'*20}")
    
    for label, rpm in scenarios:
        rec_per_day = rpm * 60 * 24
        days_needed = remaining_records / rec_per_day
        months_needed = days_needed / 30.4
        
        if days_needed < 1.0:
            time_str = f"{days_needed * 24:.1f} hours"
        elif days_needed < 60:
            time_str = f"{days_needed:.1f} days"
        else:
            time_str = f"{months_needed:.1f} months ({days_needed:.0f} days)"
            
        print(f"{label:<55} | {int(rec_per_day):<14,} | {time_str}")
        
    print("==================================================================")
    print("🏆 TOP 10 STATES BY REMAINING RECORDS")
    print("==================================================================")
    sorted_st = sorted(state_breakdown.items(), key=lambda x: (x[1]['total_msme'] - x[1]['extracted']), reverse=True)
    for code, data in sorted_st[:10]:
        rem = max(0, data['total_msme'] - data['extracted'])
        pct = (data['extracted'] / data['total_msme'] * 100) if data['total_msme'] > 0 else 0
        name = data['name'][:22]
        print(f"{code:<4} {name:<22} | Total: {int(data['total_msme']):>9,} | Done: {int(data['extracted']):>8,} ({pct:4.1f}%) | Rem: {int(rem):>9,} | Dists: {data['completed']}/{data['districts']}")
    print("==================================================================")

if __name__ == '__main__':
    analyze()
