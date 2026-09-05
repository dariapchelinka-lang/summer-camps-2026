# src/worker.py
import json
import os
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

async def on_fetch(request, env):
    url = request.url
    path = url.path
    
    if path == '/api/submit' and request.method == 'POST':
        return await handle_submit(request, env)
    
    return Response("Not found", status=404)

async def handle_submit(request, env):
    try:
        form_data = await request.form()
        values = {
            "date": datetime.now().isoformat(),
            "name": form_data.get('name', ''),
            "budget": form_data.get('budget', ''),
            # ... остальные поля
        }
        
        # Подключение к Google Sheets
        creds_json = env.GOOGLE_SERVICE_ACCOUNT_JSON
        if creds_json:
            creds_dict = json.loads(creds_json)
            scope = ['https://spreadsheets.google.com/feeds']
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(credentials)
            sheet = client.open_by_key(env.GOOGLE_SHEET_ID).sheet1
            sheet.append_row(list(values.values()))
        
        return Response(json.dumps({"success": True}), 
                       headers={"Content-Type": "application/json"})
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), 
                       status=500,
                       headers={"Content-Type": "application/json"})
