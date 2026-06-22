from langsmith import Client
import os 
from dotenv import load_dotenv

load_dotenv()

def pull_prompt_from_langsmith(prompt_name: str):
    ls_client = Client(api_key=os.getenv("LANGSMITH_API_KEY"))
    prompt = ls_client.pull_prompt(prompt_name)
    return prompt 