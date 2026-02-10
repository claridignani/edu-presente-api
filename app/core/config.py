import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL") or "mysql+mysqldb://root:java2022@localhost/edu_presente"