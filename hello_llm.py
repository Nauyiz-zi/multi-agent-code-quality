from llm import chat

print(chat([
        {"role":"system","content":"你是一个简洁的助手。"},
        {"role":"user","content":"用一句话解释什么是 AI Agent。"},
    ]))