from src.prompt import * 
from src.llms import *

def construct_flash_cards(content: str, number_of_cards: int):
    prompt = pull_prompt_from_langsmith("flash-cards-sherpo-academy-prompt")
    formatted_prompt = prompt(content = content, number_of_cards = number_of_cards)
    response = gpt.invoke(formatted_prompt).content
    return response
