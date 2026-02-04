import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

files = [os.path.join(BASE_DIR, f"batch {i}.xlsx") for i in range(1, 11)]

dfs = [pd.read_excel(f) for f in files]

combined_df = pd.concat(dfs, ignore_index=True)

combined_df.to_excel(
    os.path.join(BASE_DIR, "combined_batches.xlsx"),
    index=False
)

print("✅ Combined batch 1 to batch 10 (Excel files)")
