from pathlib import Path
import sys, time
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from run_pipeline import DATE_RE, USER_RE, PRODUCT_RE, EURO_RE

N=100_000
lines = pd.Series(
    [f'INFO payload {{"date":"2023-01-{(i%28)+1:02d}","user_id":"U-{i%25000:05d}","product_id":"P-{i%1000:04d}","euro_value":{(i%1000)+0.25:.2f}}}' for i in range(N)],
    dtype='string'
)
start=time.perf_counter()
parsed=pd.DataFrame({
    'Date': lines.str.extract(DATE_RE, expand=False),
    'User_ID': lines.str.extract(USER_RE, expand=False),
    'Product_ID': lines.str.extract(PRODUCT_RE, expand=False),
    'Euro_Value': lines.str.extract(EURO_RE, expand=False),
})
parsed['Date']=pd.to_datetime(parsed['Date'],errors='coerce')
parsed['Euro_Value']=pd.to_numeric(parsed['Euro_Value'],errors='coerce')
elapsed=time.perf_counter()-start
print(f'Parsed rows: {parsed.notna().all(axis=1).sum():,}/{N:,}')
print(f'Regex parsing benchmark: {elapsed:.3f}s')
print('PASS' if elapsed < 120 else 'FAIL')
