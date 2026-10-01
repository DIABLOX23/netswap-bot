import { executeSwapAction } from './actions/swap';
import { rebalancePortfolioAction } from './actions/rebalance';

export const aeternaPlugin = {
  name: '@aeterna/eliza-plugin',
  description: 'MEV-Protected Financial Layer & Intent-Based Trading Plugin for Eliza AI Agents',
  actions: [
    executeSwapAction,
    rebalancePortfolioAction
  ],
  evaluators: [],
  providers: []
};

export default aeternaPlugin;
