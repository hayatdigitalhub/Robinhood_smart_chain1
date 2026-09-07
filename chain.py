import requests
from web3 import Web3
from config import Config

TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()

class RobinhoodChain:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(Config.RH_RPC_URL, request_kwargs={"timeout":20}))

    def rpc(self, method, params):
        r = requests.post(Config.RH_RPC_URL,
            json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=20)
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(d["error"])
        return d["result"]

    def get_receipt(self, h):
        return self.rpc("eth_getTransactionReceipt",[h])

    def get_block(self, n):
        return self.rpc("eth_getBlockByNumber",[hex(n),False])

    def receipt_transfers(self, receipt):
        out=[]
        for log in receipt.get("logs",[]):
            topics=log.get("topics",[])
            if len(topics)<3 or topics[0].lower()!=TRANSFER_TOPIC.lower():
                continue
            out.append({
                "token":log["address"].lower(),
                "from":"0x"+topics[1][-40:].lower(),
                "to":"0x"+topics[2][-40:].lower(),
                "amount_raw":int(topics[3],16) if len(topics)>3 else 0
            })
        return out
