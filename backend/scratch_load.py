import google.oauth2.service_account
import googleapiclient.discovery
import duckdb
from app.core.config import settings

print("Fetching credentials...")
creds = google.oauth2.service_account.Credentials.from_service_account_file(
    settings.google_application_credentials,
    scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
)
service = googleapiclient.discovery.build('sheets', 'v4', credentials=creds)

print("Pulling sheet values from RD26_DUMP...")
res = service.spreadsheets().values().get(spreadsheetId=settings.gsheet_id, range='RD26_DUMP').execute()
values = res.get('values', [])
if not values:
    print("No values found!")
    exit(1)

header, *data = values
print(f"Retrieved {len(data)} rows. Header row: {header}")

print("Connecting to DuckDB...")
conn = duckdb.connect(settings.duckdb_path)
conn.execute('DROP TABLE IF EXISTS rd26_dump')

col_defs = ', '.join(f'"{h}" VARCHAR' for h in header)
conn.execute(f'CREATE TABLE rd26_dump ({col_defs})')
ph = ','.join(['?'] * len(header))
norm = [tuple((row + [None] * len(header))[: len(header)]) for row in data]

print("Inserting data...")
# Bulk insert
conn.executemany(f'INSERT INTO rd26_dump VALUES ({ph})', norm)
print(f"Successfully inserted {len(norm)} rows!")
conn.execute("INSERT OR REPLACE INTO meta VALUES ('last_refresh', now())")
conn.execute("INSERT OR REPLACE INTO meta VALUES ('source', 'gsheets')")
print("Meta values written.")
