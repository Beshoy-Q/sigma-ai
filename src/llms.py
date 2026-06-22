from langchain_openai import ChatOpenAI
from langchain_deepseek import ChatDeepSeek

gpt = ChatOpenAI(
    model="gpt-5-mini",
    temperature=0.0,
)

deepseek = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.0,
)