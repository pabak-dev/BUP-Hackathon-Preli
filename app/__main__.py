import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()
uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), access_log=False)
