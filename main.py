import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Access environment variables

api_key = os.getenv('API_KEY')
debug = os.getenv('DEBUG')


print(api_key)
print(debug)
