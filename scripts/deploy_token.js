/**
 * 1-CLICK AETERNA TOKEN DEPLOYMENT SCRIPT (BASE MAINNET)
 * ====================================================
 * Automatically deploys the compiled AeternaToken ($AET) to Base.
 * 
 * Usage:
 *   node scripts/deploy_token.js <PRIVATE_KEY>
 *   OR set DEPLOYER_PRIVATE_KEY in .env
 */

const { ethers } = require('ethers');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

const RPC_URL = process.env.BASE_RPC || 'https://mainnet.base.org';
const BUILD_PATH = path.resolve(__dirname, '..', 'build', 'AeternaToken.json');

async function main() {
  const privateKey = process.argv[2] || process.env.DEPLOYER_PRIVATE_KEY;

  if (!privateKey) {
    console.error('ERROR: Missing Private Key.');
    console.log('Usage: node scripts/deploy_token.js <YOUR_PRIVATE_KEY>');
    console.log('Or set DEPLOYER_PRIVATE_KEY in your .env file.');
    process.exit(1);
  }

  const cleanKey = privateKey.startsWith('0x') ? privateKey : `0x${privateKey}`;
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(cleanKey, provider);

  console.log('====================================================');
  console.log('⚔️  AETERNA 1-CLICK DEPLOYER');
  console.log('====================================================');
  console.log('Deployer Address:', wallet.address);

  const balance = await provider.getBalance(wallet.address);
  const ethBalance = ethers.formatEther(balance);
  console.log(`Base ETH Balance: ${ethBalance} ETH`);

  if (balance === 0n) {
    console.error('\n❌ CANNOT DEPLOY: Balance is 0 ETH. You need ~$2-$3 in Base ETH for gas.');
    process.exit(1);
  }

  if (!fs.existsSync(BUILD_PATH)) {
    console.error('ERROR: Build artifact missing. Run `node scripts/compile_token.js` first.');
    process.exit(1);
  }

  const { abi, bytecode } = JSON.parse(fs.readFileSync(BUILD_PATH, 'utf8'));

  console.log('\nDeploying AeternaToken ($AET) to Base Mainnet...');
  const factory = new ethers.ContractFactory(abi, bytecode, wallet);
  
  const deployTx = await factory.deploy();
  console.log('Transaction Broadcasted! Tx Hash:', deployTx.deploymentTransaction().hash);
  console.log('Waiting for block confirmation on Base...');

  await deployTx.waitForDeployment();
  const deployedAddress = await deployTx.getAddress();

  console.log('\n🎉 SUCCESS! AETERNA TOKEN IS LIVE ON BASE MAINNET!');
  console.log('----------------------------------------------------');
  console.log('Contract Address:', deployedAddress);
  console.log(`BaseScan Link:    https://basescan.org/token/${deployedAddress}`);
  console.log('----------------------------------------------------');
  console.log('Your 10% Founder allocation (100,000,000 $AET) is already in 0xcC12Fd53A0bA26F42Fea6Ff8B285a77Aa54B170d');
  console.log('Your 75% Pool allocation (750,000,000 $AET) is in your deployer wallet ready for LP seeding.');
  console.log('====================================================');

  // Save deployed address to config
  const deployedConfig = path.resolve(__dirname, '..', 'deployed_aeterna.json');
  fs.writeFileSync(deployedConfig, JSON.stringify({
    address: deployedAddress,
    network: 'base',
    deployedAt: new Date().toISOString(),
    txHash: deployTx.deploymentTransaction().hash
  }, null, 2));
}

main().catch(err => {
  console.error('\nDeployment Failed:', err.message);
  process.exit(1);
});
