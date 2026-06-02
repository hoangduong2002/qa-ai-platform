from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
import os

#load_dotenv()

#llm = ChatDeepSeek(
#    model="deepseek-chat",
#    api_key=os.getenv("DEEPSEEK_API_KEY"),
#    temperature=0
#)

def get_llm():

    return ChatDeepSeek(
        model="deepseek-chat",
        temperature=0
    )