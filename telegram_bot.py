import requests

class TelegramBot:
    def __init__(self, token, chat_id):
        self.token=token
        self.chat_id=chat_id

    def send(self,text):
        if not(self.token and self.chat_id):
            print(text)
            return False
        try:
            r=requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id":self.chat_id,"text":text,"disable_web_page_preview":True},
                timeout=15)
            r.raise_for_status()
            return True
        except Exception as e:
            print("Telegram error:",e)
            return False
