import os
from dotenv import load_dotenv

load_dotenv()

from app.data.sources.google_sheets import GoogleSheetsSource

try:
    source = GoogleSheetsSource()
    print("Successfully connected!")
    print(f"Spreadsheet ID: {source._sheet.get(spreadsheetId=os.environ.get('GSHEET_ID')).execute().get('spreadsheetId')}")
    print("Tab titles:", source._titles)
except Exception as e:
    print(f"Error: {e}")
