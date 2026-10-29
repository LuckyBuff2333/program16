with open('d:/program16/src/api/routes/testing.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Remove the extra-indented lines that were inside the old for loop
# Lines 5282-5283 (0-indexed 5281-5282) have 12 spaces indent but are no longer in a loop
# These were: batch_ok = ... and yield batch_done
new_lines = []
for i, line in enumerate(lines):
    if i == 5281:  # Line 5282 (0-indexed): "            batch_ok = ..."
        print(f"Removing line {i+1}: {line[:80].strip()}")
        continue
    if i == 5282:  # Line 5283 (0-indexed): "            yield f\"data:...batch_done..."
        print(f"Removing line {i+1}: {line[:80].strip()}")
        continue
    new_lines.append(line)

with open('d:/program16/src/api/routes/testing.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print("Fixed")
