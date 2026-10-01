const fs = require('fs');
const path = require('path');
const solc = require('solc');

const contractPath = path.resolve(__dirname, '..', 'contracts', 'AeternaToken.sol');
const source = fs.readFileSync(contractPath, 'utf8');

const input = {
  language: 'Solidity',
  sources: {
    'AeternaToken.sol': {
      content: source,
    },
  },
  settings: {
    optimizer: {
      enabled: true,
      runs: 200,
    },
    outputSelection: {
      '*': {
        '*': ['abi', 'evm.bytecode'],
      },
    },
  },
};

console.log('Compiling AeternaToken.sol...');
const output = JSON.parse(solc.compile(JSON.stringify(input)));

if (output.errors) {
  let hasError = false;
  output.errors.forEach(err => {
    console.log(err.formattedMessage);
    if (err.severity === 'error') hasError = true;
  });
  if (hasError) process.exit(1);
}

const contract = output.contracts['AeternaToken.sol']['AeternaToken'];
const abi = contract.abi;
const bytecode = contract.evm.bytecode.object;

const buildDir = path.resolve(__dirname, '..', 'build');
if (!fs.existsSync(buildDir)) fs.mkdirSync(buildDir);

fs.writeFileSync(
  path.resolve(buildDir, 'AeternaToken.json'),
  JSON.stringify({ abi, bytecode }, null, 2)
);

console.log('SUCCESS: AeternaToken compiled! Bytecode length:', bytecode.length);
