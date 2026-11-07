import os
import csv
from pathlib import Path

def clean_failed_folder(failed_dir):
    failed_path = Path(failed_dir)
    if not failed_path.exists():
        print(f"Directory {failed_dir} does not exist.")
        return

    # Iterate through all subdirectories
    for subdir in failed_path.iterdir():
        if not subdir.is_dir():
            continue

        print(f"Processing {subdir.name}...")

        # Process CSV files
        for csv_file in subdir.glob("*.csv"):
            temp_file = csv_file.with_name(csv_file.name + ".tmp")
            try:
                with open(csv_file, 'r', newline='', encoding='utf-8') as infile, \
                     open(temp_file, 'w', newline='', encoding='utf-8') as outfile:
                    reader = csv.reader(infile)
                    writer = csv.writer(outfile)

                    header = next(reader, None)
                    if header:
                        writer.writerow(header)

                    removed_count = 0
                    for row in reader:
                        # Check if "Not Found" is in any column (typically column 1 for Status)
                        if any("Not Found" in str(col) for col in row):
                            writer.writerow(row)
                        else:
                            removed_count += 1
                
                # Replace the original CSV with the filtered one
                temp_file.replace(csv_file)
                print(f"  Cleaned CSV {csv_file.name}: removed {removed_count} entries.")
            except Exception as e:
                print(f"  Error processing CSV {csv_file.name}: {e}")
                if temp_file.exists():
                    temp_file.unlink()

        # Process PNG files
        png_removed = 0
        for png_file in subdir.glob("*.png"):
            if "NotFound" not in png_file.name and "Not Found" not in png_file.name:
                try:
                    png_file.unlink()
                    png_removed += 1
                except Exception as e:
                    print(f"  Error deleting PNG {png_file.name}: {e}")
        
        print(f"  Removed {png_removed} non-'Not Found' PNG files.")

if __name__ == "__main__":
    failed_folder = r"c:\python_works\udayam\failed"
    clean_failed_folder(failed_folder)
    print("Cleanup complete.")
