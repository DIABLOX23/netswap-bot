"""
AETERNA PROTOCOL - GOVERNANCE & SAFE TRANSACTION PAYLOAD GENERATOR
==================================================================
Generates deterministic transaction payloads for Gnosis Safe multisig execution:
1. Safe.enableModule(aeternaModuleAddress)
2. AeternaCascadeSafeModule.registerLegacyVault(...)
"""

from web3 import Web3

# Standard Gnosis Safe ABI fragment for enabling a module
SAFE_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "module", "type": "address"}],
        "name": "enableModule",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# Aeterna Module ABI fragment for registering a vault / continuity plan
AETERNA_MODULE_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "safe", "type": "address"},
            {"internalType": "address", "name": "primaryHeir", "type": "address"},
            {"internalType": "address", "name": "emergencyColdStorage", "type": "address"},
            {"internalType": "uint256", "name": "heartbeatPeriod", "type": "uint256"},
            {"internalType": "uint256", "name": "guardianQuorum", "type": "uint256"},
            {"internalType": "address[]", "name": "guardians", "type": "address[]"},
            {"internalType": "bool", "name": "floatYieldEnabled", "type": "bool"}
        ],
        "name": "registerLegacyVault",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

def generate_payloads(
    safe_address: str,
    module_address: str,
    backup_cold_storage: str,
    heartbeat_days: int,
    quorum: int,
    guardian_addresses: list[str],
    yield_enabled: bool = False
):
    w3 = Web3()
    safe_contract = w3.eth.contract(abi=SAFE_ABI)
    module_contract = w3.eth.contract(abi=AETERNA_MODULE_ABI)

    # 1. Enable Module Calldata
    enable_calldata = safe_contract.encode_abi(
        "enableModule",
        [Web3.to_checksum_address(module_address)]
    )

    # 2. Register Vault Calldata
    heartbeat_seconds = heartbeat_days * 86400
    guardians_checksum = [Web3.to_checksum_address(g) for g in guardian_addresses]
    
    register_calldata = module_contract.encode_abi(
        "registerLegacyVault",
        [
            Web3.to_checksum_address(safe_address),
            Web3.to_checksum_address(backup_cold_storage),
            Web3.to_checksum_address(backup_cold_storage),
            heartbeat_seconds,
            quorum,
            guardians_checksum,
            yield_enabled
        ]
    )

    return {
        "safe_address": safe_address,
        "module_address": module_address,
        "enable_module_tx": {
            "to": safe_address,
            "value": 0,
            "data": enable_calldata,
            "operation": 0 # Call
        },
        "register_vault_tx": {
            "to": module_address,
            "value": 0,
            "data": register_calldata,
            "operation": 0 # Call
        }
    }

if __name__ == "__main__":
    # Example Test Run
    demo_safe = "0x1111111111111111111111111111111111111111"
    demo_module = "0x2222222222222222222222222222222222222222"
    demo_cold_storage = "0x3333333333333333333333333333333333333333"
    demo_guardians = [
        "0x4444444444444444444444444444444444444441",
        "0x4444444444444444444444444444444444444442",
        "0x4444444444444444444444444444444444444443",
        "0x4444444444444444444444444444444444444444",
        "0x4444444444444444444444444444444444444445"
    ]

    res = generate_payloads(
        demo_safe,
        demo_module,
        demo_cold_storage,
        heartbeat_days=90,
        quorum=3,
        guardian_addresses=demo_guardians
    )
    print("Payload Generation Successful!")
    print(f"EnableModule Calldata: {res['enable_module_tx']['data'][:30]}...")
    print(f"RegisterVault Calldata: {res['register_vault_tx']['data'][:30]}...")
