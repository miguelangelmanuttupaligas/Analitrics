const fs = require('fs');

const strategyFile = process.env.LIBRECHAT_OPENID_STRATEGY_FILE || '/app/api/strategies/openidStrategy.js';
const socialLoginsFile = process.env.LIBRECHAT_SOCIAL_LOGINS_FILE || '/app/api/server/socialLogins.js';

let strategySource = fs.readFileSync(strategyFile, 'utf8');
let socialLoginsSource = fs.readFileSync(socialLoginsFile, 'utf8');

const setupAnchor = 'async function setupOpenId() {';
const retryHelper = `const getPositiveIntegerEnv = (name, fallback) => {
  const value = Number.parseInt(process.env[name], 10);
  return Number.isFinite(value) && value > 0 ? value : fallback;
};

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function discoverOpenIdConfiguration(clientMetadata) {
  const maxAttempts = getPositiveIntegerEnv('ANALITRICS_OPENID_DISCOVERY_MAX_ATTEMPTS', 12);
  const retryDelay = getPositiveIntegerEnv('ANALITRICS_OPENID_DISCOVERY_RETRY_DELAY_MS', 1000);
  const maxRetryDelay = getPositiveIntegerEnv('ANALITRICS_OPENID_DISCOVERY_MAX_DELAY_MS', 3000);
  let lastError;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      return await client.discovery(
        new URL(process.env.OPENID_ISSUER),
        process.env.OPENID_CLIENT_ID,
        clientMetadata,
        undefined,
        {
          [client.customFetch]: customFetch,
        },
      );
    } catch (error) {
      lastError = error;
      if (attempt === maxAttempts) {
        break;
      }

      const delay = Math.min(retryDelay * attempt, maxRetryDelay);
      logger.warn(
        '[openidStrategy] OIDC discovery failed on attempt ' + attempt + '/' + maxAttempts +
          ': ' + error.message + '. Retrying in ' + delay + 'ms.',
      );
      await sleep(delay);
    }
  }

  throw lastError;
}

${setupAnchor}`;

if (!strategySource.includes('async function discoverOpenIdConfiguration(clientMetadata) {')) {
  if (!strategySource.includes(setupAnchor)) {
    throw new Error('LibreChat OpenID discovery patch anchor not found');
  }
  strategySource = strategySource.replace(setupAnchor, retryHelper);
}

const discoveryCall = `    /** @type {Configuration} */
    openidConfig = await client.discovery(
      new URL(process.env.OPENID_ISSUER),
      process.env.OPENID_CLIENT_ID,
      clientMetadata,
      undefined,
      {
        [client.customFetch]: customFetch,
      },
    );`;
const hardenedDiscoveryCall = `    /** @type {Configuration} */
    openidConfig = await discoverOpenIdConfiguration(clientMetadata);`;

if (!strategySource.includes(hardenedDiscoveryCall)) {
  if (!strategySource.includes(discoveryCall)) {
    throw new Error('LibreChat OpenID discovery call patch anchor not found');
  }
  strategySource = strategySource.replace(discoveryCall, hardenedDiscoveryCall);
}

const failedConfigBlock = `  if (!config) {
    logger.error('OpenID Connect configuration failed - strategy not registered.');
    return;
  }`;
const hardenedFailedConfigBlock = `  if (!config) {
    logger.error('OpenID Connect configuration failed - strategy not registered.');
    if (isEnabled(process.env.ANALITRICS_REQUIRE_OPENID)) {
      throw new Error('OpenID Connect is required but its discovery configuration failed');
    }
    return;
  }`;

if (!socialLoginsSource.includes(hardenedFailedConfigBlock)) {
  if (!socialLoginsSource.includes(failedConfigBlock)) {
    throw new Error('LibreChat OpenID fail-closed patch anchor not found');
  }
  socialLoginsSource = socialLoginsSource.replace(failedConfigBlock, hardenedFailedConfigBlock);
}

fs.writeFileSync(strategyFile, strategySource);
fs.writeFileSync(socialLoginsFile, socialLoginsSource);
