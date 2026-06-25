from web3 import Web3
import json

w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:7545"))

contract_address = "PASTE_CONTRACT_ADDRESS"

abi = json.load(open("../build/contracts/ExamRegistry.json"))["abi"]

contract = w3.eth.contract(address=contract_address, abi=abi)
account = w3.eth.accounts[0]
